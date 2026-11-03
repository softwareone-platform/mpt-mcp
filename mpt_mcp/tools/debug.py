import logging

from fastmcp import FastMCP
from fastmcp.dependencies import Depends

from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.auth.token_validator import get_token_cache
from mpt_mcp.documentation import lifespan as documentation
from mpt_mcp.marketplace import endpoint_registry
from mpt_mcp.tools.annotations import READ_ONLY_LOCAL, REFRESHES_CACHE
from mpt_mcp.tools.responses import (
    CacheInfoResponse,
    RefreshCacheResponse,
    ResourcesInfoResponse,
)
from mpt_mcp.tools.results import AUTH_HEADER_HINT, OPENAPI_SPEC_LOAD_ERROR, tool_error

logger = logging.getLogger(__name__)

DEBUG_TAG = "debug"


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


async def marketplace_refresh_cache(
    # FastMCP injects the caller's credentials as a Depends(...) default
    call_context: CallContext = Depends(get_call_context),  # noqa: WPS404
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


def register_debug_tools(mcp: FastMCP) -> None:
    """Register the debug tools, tagged DEBUG_TAG so they only show with DEBUG=true."""
    for tool, title, annotations in (
        (marketplace_cache_info, "OpenAPI spec cache state", READ_ONLY_LOCAL),
        (marketplace_refresh_cache, "Refresh the OpenAPI spec cache", REFRESHES_CACHE),
        (marketplace_resources_info, "Documentation and token cache state", READ_ONLY_LOCAL),
    ):
        mcp.tool(title=title, tags={DEBUG_TAG}, annotations=annotations)(tool)
