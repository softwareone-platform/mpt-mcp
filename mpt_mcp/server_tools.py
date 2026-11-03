import logging

from fastmcp import FastMCP
from fastmcp.dependencies import Depends

from mpt_mcp import (
    audit_fields as audit_fields_module,
)
from mpt_mcp import endpoint_registry
from mpt_mcp.analytics import get_analytics_logger
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.config import config
from mpt_mcp.documentation import lifespan as documentation
from mpt_mcp.mcp_tools import (
    add_page_position,
    execute_marketplace_query,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
    fit_result_to_budget,
    tool_error,
)
from mpt_mcp.token_validator import get_token_cache
from mpt_mcp.tool_annotations import READ_ONLY_LOCAL, READ_ONLY_REMOTE, REFRESHES_CACHE
from mpt_mcp.tool_responses import (
    AuditFieldsResponse,
    CacheInfoResponse,
    QueryResponse,
    RefreshCacheResponse,
    ResourceInfoResponse,
    ResourceSchemaResponse,
    ResourcesInfoResponse,
    ResourcesResponse,
)

logger = logging.getLogger(__name__)

DEBUG_TAG = "debug"

AUTH_HEADER_HINT = (
    "Provide your API token in the X-MPT-Authorization header (HTTP) or in "
    "MARKETPLACE_API_TOKEN (stdio)"
)
OPENAPI_SPEC_LOAD_ERROR = "Failed to load OpenAPI spec"


async def marketplace_audit_fields(
    resource: str | None = None, call_context: CallContext = Depends(get_call_context)
) -> AuditFieldsResponse:
    """
    Get audit event names per resource for filtering by "when" something happened.

    Derived from the OpenAPI spec. Returns event names (e.g. created, updated, failed); paths are
    always audit.<event>.at (when) and audit.<event>.by (who). Use for queries like "orders failed
    starting when" (audit.failed.at) or "agreements created after X" (audit.created.at).
    marketplace_query adds audit to select when rql or order use these fields.

    Args:
        resource: Optional. If provided, returns events for this resource only
                  (e.g. commerce.orders). If omitted, returns all resources.
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Audit events of the resource, or of every resource
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(
            f"{OPENAPI_SPEC_LOAD_ERROR} for audit fields",
            details=str(error),
            api_endpoint=api_base_url,
        ) from error

    result = audit_fields_module.get_audit_fields(api_base_url, resource)
    if "error" in result:
        raise tool_error(result.pop("error"), **result)

    return AuditFieldsResponse.model_validate(result)


def marketplace_cache_info() -> CacheInfoResponse:
    """
    Get information about the OpenAPI spec cache.

    Only listed and callable when DEBUG=true.

    Returns:
        Cache statistics: cached files, their total size and how many are valid or expired
    """
    return CacheInfoResponse.model_validate({
        "cache_status": "enabled",
        "cache_info": endpoint_registry.get_cache_manager().get_cache_info(),
        "note": "Cache reduces startup time and allows offline operation. Cache is automatically "
        "refreshed every 24 hours.",
    })


async def marketplace_query(
    resource: str,
    rql: str = "",
    limit: int | None = None,
    offset: int | None = None,
    select: str | None = None,
    order: str | None = None,
    path_params: dict[str, str] | None = None,
    call_context: CallContext = Depends(get_call_context),
) -> QueryResponse:
    """
    Query the SoftwareOne Marketplace API using Resource Query Language (RQL).

    Supports both simple queries and advanced RQL filtering, sorting, and pagination. See
    documentation at https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language

    Available Resource Categories:
    - Catalog: catalog.products, catalog.items, catalog.listings, catalog.authorizations
    - Commerce: commerce.orders, commerce.agreements, commerce.subscriptions
    - Billing: billing.invoices, billing.statements, billing.journals, billing.ledgers
    - Accounts: accounts.accounts, accounts.buyers, accounts.sellers, accounts.users

    RQL Query Examples:
    - Pagination: limit=10, offset=0
    - Filter: rql=eq(status,Active), limit=20
    - Search: rql=ilike(name,*Microsoft*), limit=50
    - Complex: rql=and(eq(status,Completed),ilike(product.name,*Microsoft*)),
      order=-audit.created.at
    - Sort: order=-audit.created.at or order=+name

    Use marketplace_resources() to see all available resources.

    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string. Examples: eq(status,Active), ilike(name,*Microsoft*).
            Dates in UTC (YYYY-MM-DDTHH:MM:SS.mmmZ). Use the limit, offset, select and order
            arguments for pagination, fields and sorting, not this string.
        limit: Max items to return (default 10, max 100). With many items, return only the
            fields you need (select=-*,+field1,+field2) to avoid huge responses. To page on, pass
            $meta.pagination.next_offset as offset while has_more is true; it also continues a
            page cut to fit one result. A cut page sets $meta.truncated, whose suggested_limit
            fits in one result and lets you fetch the next pages in parallel.
            Ignored for resources that return a single item (path ending in a parameter, e.g.
            *.by_id).
        offset: Number of items to skip for pagination (e.g., 0, 20, 40). For data that changes
            while you page, sort with order=+audit.created.at and filter by date in rql, so new
            items do not shift the pages. Ignored for resources that return a single item.
        select: Fields of each item. The API returns a default set of fields:
            -*,+id,+product.name returns only the listed fields (start with -* to keep
            responses small); +lines adds a field omitted by default (see $meta.omitted) to the
            default set; -price removes one. Nested: +subscriptions (full), +subscriptions.id.
            id, status and name are always included when the resource has them, fields the
            resource does not have are dropped, and the audit fields rql or order use are added
            (+audit.created.at). For catalog.products include vendor as
            +vendor.id,+vendor.name (not +vendor). Without select, catalog.products returns only
            id, status, name and shortDescription.
        order: Sort order (e.g., -audit.created.at for descending, +name for ascending)
        path_params: Path parameters for resources requiring IDs
            Examples: {id: PRD-1234-5678} for catalog.products.by_id
                     {orderId: ORD-1234-5678} for commerce.orders.{orderId}.lines
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Marketplace API response: a page of items, or a single item
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    logger.info("Using API endpoint: %s", api_base_url)
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        openapi_spec = await endpoint_registry.get_openapi_spec(api_base_url)
    except Exception as error:
        raise tool_error(
            f"{OPENAPI_SPEC_LOAD_ERROR} for your endpoint",
            api_endpoint=api_base_url,
            details=str(error),
            hint=f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
        ) from error

    audit_regex = audit_fields_module.get_audit_regex(api_base_url)
    result = await execute_marketplace_query(
        resource=resource,
        rql=rql,
        limit=limit,
        offset=offset,
        select=select,
        order=order,
        path_params=path_params,
        api_client=api_client,
        endpoints_registry=endpoints_registry_data,
        analytics_logger=get_analytics_logger(),
        config=config,
        audit_regex=audit_regex,
        openapi_spec=openapi_spec,
    )
    if not isinstance(result, dict):
        return QueryResponse(result=result)

    return QueryResponse.model_validate(add_page_position(fit_result_to_budget(result)))


async def marketplace_refresh_cache(
    call_context: CallContext = Depends(get_call_context),
) -> RefreshCacheResponse:
    """
    Force refresh the OpenAPI spec cache of your endpoint.

    Only listed and callable when DEBUG=true.

    Use this to manually update the endpoint registry if you know the API has changed.

    Returns:
        Status message indicating cache refresh result
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    logger.info("Force refreshing OpenAPI spec cache...")
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(
            api_client.base_url, force_refresh=True
        )
    except Exception as error:
        raise tool_error(
            OPENAPI_SPEC_LOAD_ERROR,
            details=str(error),
            hint="Failed to refresh cache. Check network connection.",
        ) from error

    return RefreshCacheResponse(
        success=True,
        message=f"Cache refreshed successfully. Loaded {len(endpoints_registry_data)} endpoints.",
        endpoints_count=len(endpoints_registry_data),
    )


async def marketplace_resource_info(
    resource: str, call_context: CallContext = Depends(get_call_context)
) -> ResourceInfoResponse:
    """
    Get detailed information about a specific resource.

    Args:
        resource: The resource identifier (e.g., catalog.products)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Detailed information about the resource including available parameters
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(OPENAPI_SPEC_LOAD_ERROR, details=str(error)) from error

    return ResourceInfoResponse.model_validate(
        execute_marketplace_resource_info(
            resource=resource,
            endpoints_registry=endpoints_registry_data,
        )
    )


async def marketplace_resource_schema(
    resource: str, call_context: CallContext = Depends(get_call_context)
) -> ResourceSchemaResponse:
    """
    Get the response schema of a resource.

    Use marketplace_resource_info for its query and path parameters. For catalog.products use
    select=+vendor.id,+vendor.name when including vendor.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Response schema, item fields and RQL filter hints of the resource
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        spec = await endpoint_registry.get_openapi_spec(api_base_url)
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(OPENAPI_SPEC_LOAD_ERROR, details=str(error)) from error

    return ResourceSchemaResponse.model_validate(
        execute_marketplace_resource_schema(
            resource=resource,
            openapi_spec=spec,
            endpoints_registry=endpoints_registry_data,
        )
    )


async def marketplace_resources(
    category: str | None = None,
    search: str | None = None,
    call_context: CallContext = Depends(get_call_context),
) -> ResourcesResponse:
    """
    List the queryable API resources, grouped by category.

    Without a category, each resource comes with its name and summary only. Pass a category to
    get the path, description and filterable fields of its resources. A list too long for one
    result is shortened to fewer fields, and note says how to narrow it.

    Args:
        category: Only resources of this category, with their details (e.g. commerce, catalog)
        search: Only resources whose name or summary contains this text (e.g. order)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Resources by category
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(OPENAPI_SPEC_LOAD_ERROR, details=str(error)) from error

    return ResourcesResponse.model_validate(
        execute_marketplace_resources(
            api_base_url=api_base_url,
            user_id=call_context.user_id,
            endpoints_registry=endpoints_registry_data,
            category=category,
            search=search,
        )
    )


def marketplace_resources_info() -> ResourcesInfoResponse:
    """
    Get the state of the documentation and token validation caches.

    Only listed and callable when DEBUG=true.

    Returns:
        Whether each cache is enabled, with its statistics
    """
    result = {
        "documentation": {"enabled": False, "total_pages": 0, "cache_info": None},
        "token_validation": {"enabled": False, "cache_stats": None},
    }
    dc = documentation.documentation_cache
    if dc and dc.is_enabled:
        cache_info = dc.get_cache_info()
        result["documentation"] = {
            "enabled": True,
            "total_pages": cache_info.get("resource_count", 0),
            "cache_info": cache_info,
        }
    try:
        token_cache = get_token_cache()
        result["token_validation"] = {
            "enabled": True,
            "cache_stats": token_cache.get_stats(),
            "description": "Token validation cache prevents repeated API calls for authentication",
        }
    except Exception as e_inner:
        result["token_validation"] = {"enabled": False, "error": str(e_inner)}

    return ResourcesInfoResponse.model_validate(result)


def register_tools(mcp: FastMCP) -> None:
    """Register the Marketplace and debug tools."""
    for tool, title, annotations in (
        (marketplace_query, "Query a Marketplace resource", READ_ONLY_REMOTE),
        (marketplace_resources, "List Marketplace resources", READ_ONLY_REMOTE),
        (marketplace_resource_info, "Describe a Marketplace resource", READ_ONLY_REMOTE),
        (marketplace_resource_schema, "Marketplace resource schema", READ_ONLY_REMOTE),
        (marketplace_audit_fields, "Marketplace audit events", READ_ONLY_REMOTE),
    ):
        mcp.tool(title=title, annotations=annotations)(tool)
    for debug_tool, title, annotations in (
        (marketplace_cache_info, "OpenAPI spec cache state", READ_ONLY_LOCAL),
        (marketplace_refresh_cache, "Refresh the OpenAPI spec cache", REFRESHES_CACHE),
        (marketplace_resources_info, "Documentation and token cache state", READ_ONLY_LOCAL),
    ):
        mcp.tool(title=title, tags={DEBUG_TAG}, annotations=annotations)(debug_tool)
