import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from mcp_types import ToolAnnotations

from mpt_mcp import (
    audit_fields as audit_fields_module,
)
from mpt_mcp import (
    endpoint_registry,
    server_docs,
)
from mpt_mcp.analytics import get_analytics_logger
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.config import config
from mpt_mcp.mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_quick_queries,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
    tool_error,
)
from mpt_mcp.token_validator import get_token_cache

logger = logging.getLogger(__name__)

DEBUG_TAG = "debug"

DOCUMENTATION_CACHE_UNAVAILABLE_MSG = (
    "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
)
AUTH_HEADER_HINT = (
    "Provide your API token in the X-MPT-Authorization header (HTTP) or in "
    "MARKETPLACE_API_TOKEN (stdio)"
)
OPENAPI_SPEC_LOAD_ERROR = "Failed to load OpenAPI spec"

MANY_DOCS_RESULTS = 50

# Every tool only reads: they differ in whether they reach the Marketplace API or GitBook
READ_ONLY_LOCAL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
READ_ONLY_REMOTE = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# Refreshing rewrites the server's spec cache: it changes state, but repeating it is harmless
REFRESHES_CACHE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


async def marketplace_audit_fields(
    resource: str | None = None, call_context: CallContext = Depends(get_call_context)
) -> dict[str, Any]:
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
        If resource is set: { "resource": str, "events": [ "created", "updated", ... ] }.
        If resource is omitted:
            { "by_resource": { resource_id: [ "event1", "event2", ... ], ... } }.
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

    return result


def marketplace_cache_info() -> dict[str, Any]:
    """
    Get information about the OpenAPI spec cache.

    Only listed and callable when DEBUG=true.

    Returns:
        Cache statistics: cached files, their total size and how many are valid or expired
    """
    return {
        "cache_status": "enabled",
        "cache_info": endpoint_registry.get_cache_manager().get_cache_info(),
        "note": "Cache reduces startup time and allows offline operation. Cache is automatically "
        "refreshed every 24 hours.",
    }


async def marketplace_docs_index() -> dict[str, Any]:
    """
    Get the documentation table of contents.

    Returns:
        Total page count and the documentation sections with their subsections and page counts
    """
    await server_docs.initialize_documentation_cache()
    dc = server_docs.documentation_cache
    if not dc or not dc.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    return await dc.get_documentation_index()


async def marketplace_docs_list(
    section: str | None = None,
    subsection: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """
    List documentation pages, optionally filtered.

    Args:
        section: Only pages of this section (see marketplace_docs_index)
        subsection: Only pages of this subsection
        search: Only pages whose title or path contains this text
        limit: Max pages to return (default 100)

    Returns:
        Matching pages with their docs:// uri, title and public browser_url when available
    """
    await server_docs.initialize_documentation_cache()
    dc = server_docs.documentation_cache
    if not dc or not dc.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    resources = await dc.list_resources(
        section=section, subsection=subsection, search=search, limit=limit
    )
    resources_for_response = []
    for resource in resources:
        entry = dict(resource)
        if resource.get("metadata", {}).get("browser_url"):
            entry["browser_url"] = resource["metadata"]["browser_url"]
        resources_for_response.append(entry)
    filters = []
    if section:
        filters.append(f"section={section}")
    if subsection:
        filters.append(f"subsection={subsection}")
    if search:
        filters.append(f"search='{search}'")
    result = {
        "total": len(resources_for_response),
        "resources": resources_for_response,
        "filters_applied": ", ".join(filters) if filters else "none",
        "usage": (
            "Use marketplace_docs_read(uri='docs://path') to read a page. "
            "Prefer showing users the browser_url (public link) when present; "
            "do not show internal uri or id to end users."
        ),
    }
    if len(resources) >= limit:
        result["tip"] = (
            f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
        )
    elif len(resources) > MANY_DOCS_RESULTS:
        result["tip"] = "Consider using 'section' or 'subsection' filters to narrow down results."

    return result


async def marketplace_docs_read(uri: str) -> dict[str, Any]:
    """
    Read a documentation page.

    Args:
        uri: Page uri from marketplace_docs_list (e.g. docs://help-and-support/contact-support)

    Returns:
        {"text": "<markdown content>", "count": 1}
    """
    await server_docs.initialize_documentation_cache()
    dc = server_docs.documentation_cache
    if not dc or not dc.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    page_content = await dc.get_resource(uri)
    if page_content is None:
        raise tool_error(
            f"Documentation page not found: {uri}",
            hint="Use marketplace_docs_list() to see available pages.",
        )

    return {"text": page_content, "count": 1}


async def marketplace_query(
    resource: str,
    rql: str = "",
    limit: int | None = None,
    offset: int | None = None,
    select: str | None = None,
    order: str | None = None,
    path_params: dict[str, str] | None = None,
    call_context: CallContext = Depends(get_call_context),
) -> dict[str, Any]:
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
        limit: Max items to return (default 10, max 100). Use select= with only needed fields
            (from marketplace_resource_schema) to avoid huge responses. Ignored for resources
            that return a single item (path ending in a parameter, e.g. *.by_id).
        offset: Number of items to skip for pagination (e.g., 0, 20, 40). Ignored for
            resources that return a single item.
        select: Fields to include/exclude (+name,+description or -metadata). 'audit' is added
            automatically when rql or order use audit fields. Nested: +subscriptions (full),
            +subscriptions.id, +subscriptions.id,+subscriptions.name.
            For catalog.products when including vendor use +vendor.id,+vendor.name (not +vendor).
            RQL filter fields must exist—use marketplace_resource_schema(resource) to check.
        order: Sort order (e.g., -audit.created.at for descending, +name for ascending)
        path_params: Path parameters for resources requiring IDs
            Examples: {id: PRD-1234-5678} for catalog.products.by_id
                     {orderId: ORD-1234-5678} for commerce.orders.{orderId}.lines
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        API response with data and pagination information
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
    return await execute_marketplace_query(
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


def marketplace_quick_queries() -> dict[str, Any]:
    """
    Get pre-built query templates for common use cases.

    Returns ready-to-use query examples organized by category. These templates
    help you quickly perform common tasks without learning RQL syntax.

    Example: marketplace_quick_queries() shows templates for finding recent
    orders, active products, specific vendors, etc.

    Returns:
        Dictionary of query templates organized by category
    """
    return execute_marketplace_quick_queries()


async def marketplace_refresh_cache(
    call_context: CallContext = Depends(get_call_context),
) -> dict[str, Any]:
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
    endpoints_registry_data = await endpoint_registry.get_endpoints_registry(
        api_client.base_url, force_refresh=True
    )
    if not endpoints_registry_data:
        raise tool_error(
            OPENAPI_SPEC_LOAD_ERROR, hint="Failed to refresh cache. Check network connection."
        )

    return {
        "success": True,
        "message": (
            f"Cache refreshed successfully. Loaded {len(endpoints_registry_data)} endpoints."
        ),
        "endpoints_count": len(endpoints_registry_data),
    }


async def marketplace_resource_info(
    resource: str, call_context: CallContext = Depends(get_call_context)
) -> dict[str, Any]:
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

    return execute_marketplace_resource_info(
        resource=resource,
        endpoints_registry=endpoints_registry_data,
    )


async def marketplace_resource_schema(
    resource: str, call_context: CallContext = Depends(get_call_context)
) -> dict[str, Any]:
    """
    Get the response schema of a resource.

    Use marketplace_resource_info for its query and path parameters. For catalog.products use
    select=+vendor.id,+vendor.name when including vendor.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        The response schema from the OpenAPI spec, its top-level fields with type, description,
        enum values and format, RQL filter hints built from those fields, and common query
        patterns
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

    return execute_marketplace_resource_schema(
        resource=resource,
        openapi_spec=spec,
        endpoints_registry=endpoints_registry_data,
    )


async def marketplace_resources(
    call_context: CallContext = Depends(get_call_context),
) -> dict[str, Any]:
    """
    List all available API resources.

    Returns:
        A categorized list of all available API endpoints
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

    return execute_marketplace_resources(
        api_base_url=api_base_url,
        user_id=call_context.user_id,
        endpoints_registry=endpoints_registry_data,
    )


def marketplace_resources_info() -> dict[str, Any]:
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
    dc = server_docs.documentation_cache
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

    return result


def register_tools(mcp: FastMCP) -> None:
    """Register the Marketplace, documentation and debug tools."""
    for tool, title, annotations in (
        (marketplace_query, "Query a Marketplace resource", READ_ONLY_REMOTE),
        (marketplace_quick_queries, "Marketplace query templates", READ_ONLY_LOCAL),
        (marketplace_resources, "List Marketplace resources", READ_ONLY_REMOTE),
        (marketplace_resource_info, "Describe a Marketplace resource", READ_ONLY_REMOTE),
        (marketplace_resource_schema, "Marketplace resource schema", READ_ONLY_REMOTE),
        (marketplace_audit_fields, "Marketplace audit events", READ_ONLY_REMOTE),
        (marketplace_docs_index, "Documentation index", READ_ONLY_REMOTE),
        (marketplace_docs_list, "List documentation pages", READ_ONLY_REMOTE),
        (marketplace_docs_read, "Read a documentation page", READ_ONLY_REMOTE),
    ):
        mcp.tool(title=title, annotations=annotations)(tool)
    for debug_tool, title, annotations in (
        (marketplace_cache_info, "OpenAPI spec cache state", READ_ONLY_LOCAL),
        (marketplace_refresh_cache, "Refresh the OpenAPI spec cache", REFRESHES_CACHE),
        (marketplace_resources_info, "Documentation and token cache state", READ_ONLY_LOCAL),
    ):
        mcp.tool(title=title, tags={DEBUG_TAG}, annotations=annotations)(debug_tool)
