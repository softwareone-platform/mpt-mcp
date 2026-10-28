import json
from typing import Any

from fastmcp.dependencies import Depends

from mpt_mcp import endpoint_registry, server_docs
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.token_validator import validate_token


async def get_openapi_spec(call_context: CallContext = Depends(get_call_context)) -> str:
    """Return OpenAPI spec for the current endpoint (requires auth)."""
    token, endpoint = call_context.token, call_context.endpoint
    if not token:
        return json.dumps(
            {
                "error": "Authentication required",
                "message": "Please provide X-MPT-Authorization header to access OpenAPI specification",
                "hint": "The OpenAPI spec is specific to your API endpoint and requires authentication",
            },
            indent=2,
        )

    is_valid, token_info, error = await validate_token(token, endpoint)
    if not is_valid:
        return json.dumps(
            {
                "error": "Invalid credentials",
                "message": f"Token validation failed: {error}",
                "hint": "Please check your X-MPT-Authorization header",
            },
            indent=2,
        )

    try:
        openapi_spec = await endpoint_registry.get_openapi_spec(endpoint, force_refresh=False)
    except Exception as e:
        return json.dumps(
            {
                "error": "Failed to fetch OpenAPI specification",
                "message": str(e),
                "endpoint": endpoint,
            },
            indent=2,
        )

    if not openapi_spec:
        return json.dumps(
            {
                "error": "OpenAPI specification not available",
                "message": f"Could not load OpenAPI spec for endpoint: {endpoint}",
                "hint": "The API endpoint may be unreachable or the specification is not available",
            },
            indent=2,
        )

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


def register_http_resources(mcp: Any) -> None:
    mcp.resource(
        "api://openapi.json",
        name="OpenAPI Specification",
        description="OpenAPI 3 spec for the current API endpoint (requires auth).",
        mime_type="application/json",
    )(get_openapi_spec)

    @mcp.resource(
        "docs://{path}",
        name="Documentation",
        description="Documentation pages. Use marketplace_docs_list() for available URIs.",
        mime_type="text/markdown",
    )
    async def get_documentation_resource(path: str) -> str:
        uri = f"docs://{path}"
        await server_docs.initialize_documentation_cache()
        dc = server_docs.documentation_cache
        if not dc or not dc.is_enabled:
            return "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."

        content = await dc.get_resource(uri)
        if content is None:
            return f"Documentation page not found: {uri}"

        return content
