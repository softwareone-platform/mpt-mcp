import asyncio
import logging

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends

from mpt_mcp.config import config
from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.gitbook import GitBookClient

logger = logging.getLogger(__name__)

DOCUMENTATION_STORE_KEY = "documentation"


class DocumentationStore:
    """Documentation cache of a server, loaded once: at HTTP startup or on the first call."""

    def __init__(self) -> None:
        self._cache: DocumentationCache | None = None
        self._lock = asyncio.Lock()

    @property
    def cache(self) -> DocumentationCache | None:
        """Return the documentation cache, or None while it is not loaded."""
        return self._cache

    async def get(self) -> DocumentationCache:
        """
        Return the documentation cache, loading it on the first call.

        Returns:
            Loaded cache, or a disabled one when GitBook is not configured or cannot be reached
        """
        async with self._lock:
            if self._cache is None:
                self._cache = await load_documentation_cache()
            return self._cache


def get_documentation_store(
    context: Context = CurrentContext(),  # noqa: WPS404
) -> DocumentationStore:
    """
    Return the documentation store of the server, created by its documentation lifespan.

    Args:
        context: Context of the MCP request, injected by FastMCP

    Returns:
        Documentation store of the server
    """
    documentation_store: DocumentationStore = context.lifespan_context[DOCUMENTATION_STORE_KEY]
    return documentation_store


async def get_documentation_cache(
    documentation_store: DocumentationStore = Depends(get_documentation_store),  # noqa: WPS404
) -> DocumentationCache:
    """
    Return the documentation cache of the server, loading it on the first call.

    Args:
        documentation_store: Documentation store of the server, injected by FastMCP

    Returns:
        Documentation cache, disabled when GitBook is not configured or cannot be reached
    """
    return await documentation_store.get()


async def load_documentation_cache() -> DocumentationCache:
    """
    Create the documentation cache and load the page index from GitBook.

    Returns:
        Loaded cache, or a disabled one when GitBook is not configured or cannot be reached
    """
    logger.info("Loading documentation cache...")
    if not config.gitbook_api_key or not config.gitbook_space_id:
        logger.info(
            "GitBook not configured, documentation cache disabled (GITBOOK_API_KEY=%s, "
            "GITBOOK_SPACE_ID=%s).",
            "set" if config.gitbook_api_key else "missing",
            "set" if config.gitbook_space_id else "missing",
        )
        return DocumentationCache(gitbook_client=None)

    gitbook_client = GitBookClient(
        api_key=config.gitbook_api_key,
        space_id=config.gitbook_space_id,
        base_url=config.gitbook_api_base_url,
        max_concurrent_requests=config.gitbook_max_concurrent_requests,
    )
    if not await gitbook_client.validate_credentials():
        logger.warning("GitBook credentials invalid, documentation cache disabled")
        return DocumentationCache(gitbook_client=None)

    cache = DocumentationCache(
        gitbook_client=gitbook_client,
        refresh_interval_hours=config.gitbook_cache_refresh_hours,
        public_url=config.gitbook_public_url,
    )
    if not await cache.refresh():
        logger.warning("Documentation index not loaded; the next documentation request retries it")
        return cache

    doc_resources = await cache.list_resources()
    logger.info(
        "Documentation cache loaded (%s pages); served via docs://{path*} template",
        len(doc_resources),
    )
    logger.info("DOCS CACHE READY — marketplace_docs_list and docs:// resources are available")
    return cache
