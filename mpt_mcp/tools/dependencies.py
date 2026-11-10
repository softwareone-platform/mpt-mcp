import logging

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends

from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.auth.token_validator import TokenValidator, get_token_validator
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.tools.results import AUTH_HEADER_HINT, OPENAPI_SPEC_LOAD_ERROR, tool_error
from mpt_mcp.tools.spec import MarketplaceSpec
from mpt_mcp.tools.spec_store import SPEC_STORE_KEY, MarketplaceSpecStore

logger = logging.getLogger(__name__)


async def get_api_client(
    call_context: CallContext = Depends(get_call_context),  # noqa: WPS404
    token_validator: TokenValidator = Depends(get_token_validator),  # noqa: WPS404
) -> APIClient:
    """
    Create the API client of the caller, for the tools that call the Marketplace API.

    Args:
        call_context: Caller's credentials, injected by FastMCP
        token_validator: Token validator of the server, injected by FastMCP

    Returns:
        API client authenticated with the caller's token

    Raises:
        ToolError: The token is missing or fails validation
    """
    try:
        api_client = await call_context.create_api_client(token_validator)
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    logger.info("Using API endpoint: %s", api_client.base_url)
    return api_client


def get_spec_store(context: Context = CurrentContext()) -> MarketplaceSpecStore:  # noqa: WPS404
    """
    Return the spec store of the server, created by spec_lifespan.

    Args:
        context: Context of the MCP request, injected by FastMCP

    Returns:
        Specs of the callers' endpoints
    """
    spec_store: MarketplaceSpecStore = context.lifespan_context[SPEC_STORE_KEY]
    return spec_store


async def get_marketplace_spec(
    api_client: APIClient = Depends(get_api_client),  # noqa: WPS404
    spec_store: MarketplaceSpecStore = Depends(get_spec_store),  # noqa: WPS404
) -> MarketplaceSpec:
    """
    Load the OpenAPI spec of the caller's endpoint.

    Args:
        api_client: Caller's API client, injected by FastMCP
        spec_store: Specs of the callers' endpoints, injected by FastMCP

    Returns:
        Spec, endpoints registry and audit events of the endpoint

    Raises:
        ToolError: The spec cannot be loaded
    """
    api_base_url = api_client.base_url
    try:
        return await spec_store.get(api_base_url)
    except OpenAPISpecFetchError as error:
        raise tool_error(
            f"{OPENAPI_SPEC_LOAD_ERROR} for your endpoint",
            api_endpoint=api_base_url,
            details=str(error),
            hint=f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
        ) from error
