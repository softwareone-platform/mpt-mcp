import logging

from fastmcp.dependencies import Depends
from fastmcp.server.providers import LocalProvider

from mpt_mcp.auth.token_validator import get_token_cache
from mpt_mcp.documentation.store import DocumentationStore, get_documentation_store
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.tools.annotations import READ_ONLY_LOCAL, REFRESHES_CACHE
from mpt_mcp.tools.dependencies import get_api_client, get_spec_store
from mpt_mcp.tools.responses import (
    CacheInfoResponse,
    DocumentationCacheState,
    RefreshCacheResponse,
    ResourcesInfoResponse,
    SpecCacheInfo,
    TokenCacheState,
)
from mpt_mcp.tools.results import OPENAPI_SPEC_LOAD_ERROR, tool_error
from mpt_mcp.tools.spec_store import MarketplaceSpecStore

logger = logging.getLogger(__name__)
debug_tools = LocalProvider()

DEBUG_TAG = "debug"


@debug_tools.tool(title="OpenAPI spec cache state", tags={DEBUG_TAG}, annotations=READ_ONLY_LOCAL)
def marketplace_cache_info(
    spec_store: MarketplaceSpecStore = Depends(get_spec_store),  # noqa: WPS404
) -> CacheInfoResponse:
    """
    Get information about the OpenAPI spec cache.

    Only listed and callable when DEBUG=true.

    Args:
        spec_store: Specs of the callers' endpoints, injected by FastMCP (not a tool argument)

    Returns:
        Cache statistics: cached files, their total size and how many are valid or expired
    """
    return CacheInfoResponse(
        cache_status="enabled",
        cache_info=SpecCacheInfo.model_validate(spec_store.cache_manager.get_cache_info()),
        note=(
            "Cache reduces startup time and allows offline operation. Cache is automatically "
            "refreshed every 24 hours."
        ),
    )


@debug_tools.tool(
    title="Refresh the OpenAPI spec cache", tags={DEBUG_TAG}, annotations=REFRESHES_CACHE
)
async def marketplace_refresh_cache(
    api_client: APIClient = Depends(get_api_client),  # noqa: WPS404
    spec_store: MarketplaceSpecStore = Depends(get_spec_store),  # noqa: WPS404
) -> RefreshCacheResponse:
    """
    Force refresh the OpenAPI spec cache of your endpoint.

    Only listed and callable when DEBUG=true.

    Use this to manually update the endpoint registry if you know the API has changed.

    Args:
        api_client: Caller's API client, injected by FastMCP (not a tool argument)
        spec_store: Specs of the callers' endpoints, injected by FastMCP (not a tool argument)

    Returns:
        Status message indicating cache refresh result
    """
    logger.info("Force refreshing OpenAPI spec cache...")
    try:
        spec = await spec_store.get(api_client.base_url, force_refresh=True)
    except OpenAPISpecFetchError as error:
        raise tool_error(
            OPENAPI_SPEC_LOAD_ERROR,
            details=str(error),
            hint="Failed to refresh cache. Check network connection.",
        ) from error

    endpoints_count = len(spec.endpoints_registry)
    return RefreshCacheResponse(
        success=True,
        message=f"Cache refreshed successfully. Loaded {endpoints_count} endpoints.",
        endpoints_count=endpoints_count,
    )


@debug_tools.tool(
    title="Documentation and token cache state", tags={DEBUG_TAG}, annotations=READ_ONLY_LOCAL
)
def marketplace_resources_info(
    documentation_store: DocumentationStore = Depends(get_documentation_store),  # noqa: WPS404
) -> ResourcesInfoResponse:
    """
    Get the state of the documentation and token validation caches.

    Only listed and callable when DEBUG=true.

    Args:
        documentation_store: Documentation store of the server, injected by FastMCP (not a tool
            argument)

    Returns:
        Whether each cache is enabled, with its statistics
    """
    documentation_state = DocumentationCacheState(enabled=False, total_pages=0)
    docs_cache = documentation_store.cache
    if docs_cache and docs_cache.is_enabled:
        cache_info = docs_cache.get_cache_info()
        documentation_state = DocumentationCacheState(
            enabled=True, total_pages=cache_info.get("resource_count", 0), cache_info=cache_info
        )
    return ResourcesInfoResponse(
        documentation=documentation_state,
        token_validation=TokenCacheState(
            enabled=True,
            cache_stats=get_token_cache().get_stats(),
            description="Token validation cache prevents repeated API calls for authentication",
        ),
    )
