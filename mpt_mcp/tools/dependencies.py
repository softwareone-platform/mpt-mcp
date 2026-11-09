import logging

from fastmcp.dependencies import Depends

from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.marketplace import audit_fields
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.endpoint_registry import (
    OpenAPISpecFetchError,
    get_endpoints_registry,
    get_openapi_spec,
)
from mpt_mcp.marketplace.schemas import OpenAPISpec
from mpt_mcp.tools.results import AUTH_HEADER_HINT, OPENAPI_SPEC_LOAD_ERROR, tool_error
from mpt_mcp.tools.spec import MarketplaceSpec

logger = logging.getLogger(__name__)


async def get_api_client(
    call_context: CallContext = Depends(get_call_context),  # noqa: WPS404
) -> APIClient:
    """
    Create the API client of the caller, for the tools that call the Marketplace API.

    Args:
        call_context: Caller's credentials, injected by FastMCP

    Returns:
        API client authenticated with the caller's token

    Raises:
        ToolError: The token is missing or fails validation
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    logger.info("Using API endpoint: %s", api_client.base_url)
    return api_client


async def get_marketplace_spec(
    api_client: APIClient = Depends(get_api_client),  # noqa: WPS404
) -> MarketplaceSpec:
    """
    Load the OpenAPI spec of the caller's endpoint.

    Args:
        api_client: Caller's API client, injected by FastMCP

    Returns:
        Spec, endpoints registry and audit fields of the endpoint

    Raises:
        ToolError: The spec cannot be loaded
    """
    api_base_url = api_client.base_url
    try:
        endpoints_registry = await get_endpoints_registry(api_base_url)
        openapi_spec = await get_openapi_spec(api_base_url)
    except OpenAPISpecFetchError as error:
        raise tool_error(
            f"{OPENAPI_SPEC_LOAD_ERROR} for your endpoint",
            api_endpoint=api_base_url,
            details=str(error),
            hint=f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
        ) from error

    return MarketplaceSpec(
        api_base_url=api_base_url,
        audit_regex=audit_fields.get_audit_regex(api_base_url),
        endpoints_registry=endpoints_registry,
        openapi=OpenAPISpec(openapi_spec),
    )
