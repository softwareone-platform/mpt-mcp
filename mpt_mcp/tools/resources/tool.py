from fastmcp.dependencies import Depends
from fastmcp.server.providers import LocalProvider

from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.marketplace.audit_fields import get_audit_fields
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.dependencies import MarketplaceSpec, get_marketplace_spec
from mpt_mcp.tools.endpoints import get_endpoint
from mpt_mcp.tools.resources.info import describe_resource_info
from mpt_mcp.tools.resources.listing import list_resources
from mpt_mcp.tools.resources.schema import describe_resource_schema
from mpt_mcp.tools.responses import (
    AuditFieldsResponse,
    ResourceInfoResponse,
    ResourceSchemaResponse,
    ResourcesResponse,
)
from mpt_mcp.tools.results import tool_error

resource_tools = LocalProvider()


@resource_tools.tool(title="List Marketplace resources", annotations=READ_ONLY_REMOTE)
def marketplace_resources(
    category: str | None = None,
    search: str | None = None,
    call_context: CallContext = Depends(get_call_context),  # noqa: WPS404
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
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
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Resources by category
    """
    return list_resources(
        spec.endpoints_registry,
        api_base_url=spec.api_base_url,
        user_id=call_context.user_id,
        category=category,
        search=search,
    )


@resource_tools.tool(title="Describe a Marketplace resource", annotations=READ_ONLY_REMOTE)
def marketplace_resource_info(
    resource: str,
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
) -> ResourceInfoResponse:
    """
    Get detailed information about a specific resource.

    Args:
        resource: The resource identifier (e.g., catalog.products)
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Detailed information about the resource including available parameters
    """
    endpoint_info = get_endpoint(resource, spec.endpoints_registry)
    return describe_resource_info(resource, endpoint_info, spec.endpoints_registry)


@resource_tools.tool(title="Marketplace resource schema", annotations=READ_ONLY_REMOTE)
def marketplace_resource_schema(
    resource: str,
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
) -> ResourceSchemaResponse:
    """
    Get the response schema of a resource.

    Use marketplace_resource_info for its query and path parameters. For catalog.products use
    select=+vendor.id,+vendor.name when including vendor.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Response schema, item fields and RQL filter hints of the resource
    """
    endpoint_info = get_endpoint(resource, spec.endpoints_registry)
    return describe_resource_schema(resource, endpoint_info["path"], spec)


@resource_tools.tool(title="Marketplace audit events", annotations=READ_ONLY_REMOTE)
def marketplace_audit_fields(
    resource: str | None = None,
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
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
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Audit events of the resource, or of every resource
    """
    result = get_audit_fields(spec.api_base_url, resource)
    if "error" in result:
        raise tool_error(result.pop("error"), **result)

    return AuditFieldsResponse.model_validate(result)
