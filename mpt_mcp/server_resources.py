import json

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ResourceError

from mpt_mcp import endpoint_registry, server_docs
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.token_validator import validate_token


async def get_openapi_spec(call_context: CallContext = Depends(get_call_context)) -> str:
    """
    Return the OpenAPI spec of the caller's endpoint.

    Args:
        call_context: Caller's credentials, injected by FastMCP

    Returns:
        The spec as JSON, with the endpoint and the caller's account

    Raises:
        ResourceError: The caller has no valid token or the spec could not be loaded
    """
    token, endpoint = call_context.token, call_context.endpoint
    if not token:
        raise ResourceError(
            "Authentication required: provide the X-MPT-Authorization header to read the "
            "OpenAPI spec of your endpoint"
        )

    is_valid, token_info, error = await validate_token(token, endpoint)
    if not is_valid:
        raise ResourceError(
            f"Token validation failed: {error}. Check your X-MPT-Authorization header"
        )

    try:
        openapi_spec = await endpoint_registry.get_openapi_spec(endpoint, force_refresh=False)
    except Exception as error:
        raise ResourceError(f"Failed to fetch the OpenAPI spec of {endpoint}: {error}") from error

    spec_with_metadata = {
        "api_endpoint": endpoint,
        "authenticated_as": token_info.get("account", {}).get("name", "Unknown")
        if token_info
        else "Unknown",
        "account_id": token_info.get("account", {}).get("id", "Unknown")
        if token_info
        else "Unknown",
        "openapi_version": openapi_spec.get("openapi", "3.0"),
        "info": openapi_spec.get("info", {}),
        "spec": openapi_spec,
    }
    return json.dumps(spec_with_metadata, indent=2)


async def get_documentation_page(path: str) -> str:
    """
    Return the markdown of the documentation page at docs://{path}.

    Args:
        path: Page path, the uri without docs://

    Returns:
        Page content in markdown

    Raises:
        ResourceError: The documentation is not configured or the page does not exist
    """
    uri = f"docs://{path}"
    await server_docs.initialize_documentation_cache()
    dc = server_docs.documentation_cache
    if not dc or not dc.is_enabled:
        raise ResourceError(
            "Documentation cache is not available. Please configure GITBOOK_API_KEY and "
            "GITBOOK_SPACE_ID."
        )

    page_content = await dc.get_resource(uri)
    if page_content is None:
        raise ResourceError(
            f"Documentation page not found: {uri}. Use marketplace_docs_list() to see "
            "available pages"
        )

    return page_content


def register_resources(mcp: FastMCP) -> None:
    """Register the OpenAPI spec and documentation resources."""
    mcp.resource(
        "api://openapi.json",
        name="OpenAPI Specification",
        description="OpenAPI 3 spec for the current API endpoint (requires auth).",
        mime_type="application/json",
    )(get_openapi_spec)
    mcp.resource(
        "docs://{path*}",
        name="Documentation",
        description="Documentation pages. Use marketplace_docs_list() for available URIs.",
        mime_type="text/markdown",
    )(get_documentation_page)
