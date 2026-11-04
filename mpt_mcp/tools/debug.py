import logging

from fastmcp.dependencies import Depends
from fastmcp.server.providers import LocalProvider

from mpt_mcp.auth.token_validator import get_token_cache
from mpt_mcp.documentation import lifespan as documentation
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.endpoint_registry import (
    OpenAPISpecFetchError,
    get_cache_manager,
    get_endpoints_registry,
)
from mpt_mcp.tools.annotations import READ_ONLY_LOCAL, REFRESHES_CACHE
from mpt_mcp.tools.dependencies import get_api_client
from mpt_mcp.tools.responses import (
    CacheInfoResponse,
    RefreshCacheResponse,
    ResourcesInfoResponse,
)
from mpt_mcp.tools.results import OPENAPI_SPEC_LOAD_ERROR, tool_error

logger = logging.getLogger(__name__)
debug_tools = LocalProvider()

DEBUG_TAG = "debug"


@debug_tools.tool(title="OpenAPI spec cache state", tags={DEBUG_TAG}, annotations=READ_ONLY_LOCAL)
def marketplace_cache_info() -> CacheInfoResponse:
    """
    Get information about the OpenAPI spec cache.

    Only listed and callable when DEBUG=true.

    Returns:
        Cache statistics: cached files, their total size and how many are valid or expired
    """
    return CacheInfoResponse.model_validate({
        "cache_status": "enabled",
        "cache_info": get_cache_manager().get_cache_info(),
        "note": "Cache reduces startup time and allows offline operation. Cache is automatically "
        "refreshed every 24 hours.",
    })


@debug_tools.tool(
    title="Refresh the OpenAPI spec cache", tags={DEBUG_TAG}, annotations=REFRESHES_CACHE
)
async def marketplace_refresh_cache(
    api_client: APIClient = Depends(get_api_client),  # noqa: WPS404
) -> RefreshCacheResponse:
    """
    Force refresh the OpenAPI spec cache of your endpoint.

    Only listed and callable when DEBUG=true.

    Use this to manually update the endpoint registry if you know the API has changed.

    Args:
        api_client: Caller's API client, injected by FastMCP (not a tool argument)

    Returns:
        Status message indicating cache refresh result
    """
    logger.info("Force refreshing OpenAPI spec cache...")
    try:
        endpoints_registry_data = await get_endpoints_registry(
            api_client.base_url, force_refresh=True
        )
    except OpenAPISpecFetchError as error:
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


@debug_tools.tool(
    title="Documentation and token cache state", tags={DEBUG_TAG}, annotations=READ_ONLY_LOCAL
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
    dc = documentation.documentation_state.cache
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
