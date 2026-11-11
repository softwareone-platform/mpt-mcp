import json

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ResourceError
from fastmcp.server.providers import LocalProvider

from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.auth.token_validator import TokenValidator, get_token_validator
from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.tools.dependencies import get_spec_store
from mpt_mcp.tools.spec_store import MarketplaceSpecStore

openapi_resources = LocalProvider()


@openapi_resources.resource(
    "api://openapi.json",
    name="OpenAPI Specification",
    description="OpenAPI 3 spec for the current API endpoint (requires auth).",
    mime_type="application/json",
)
async def read_openapi_spec(
    call_context: CallContext = Depends(get_call_context),  # noqa: WPS404
    spec_store: MarketplaceSpecStore = Depends(get_spec_store),  # noqa: WPS404
    token_validator: TokenValidator = Depends(get_token_validator),  # noqa: WPS404
) -> str:
    """
    Return the OpenAPI spec of the caller's endpoint.

    Args:
        call_context: Caller's credentials, injected by FastMCP
        spec_store: Specs of the callers' endpoints, injected by FastMCP
        token_validator: Token validator of the server, injected by FastMCP

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

    validation = await token_validator.validate(token, endpoint)
    if not validation.is_valid:
        raise ResourceError(
            f"Token validation failed: {validation.error}. Check your X-MPT-Authorization header"
        )

    try:
        spec = await spec_store.get(endpoint)
    except OpenAPISpecFetchError as error:
        raise ResourceError(f"Failed to fetch the OpenAPI spec of {endpoint}: {error}") from error

    spec_with_metadata = {
        "api_endpoint": endpoint,
        "authenticated_as": validation.account.get("name", "Unknown"),
        "account_id": validation.account.get("id", "Unknown"),
        "openapi_version": spec.openapi.version,
        "info": spec.openapi.api_info,
        "spec": spec.openapi.document,
    }
    return json.dumps(spec_with_metadata, indent=2)
