from __future__ import annotations

import logging
import os
from functools import partial
from typing import TYPE_CHECKING, Any

from fastmcp.resources import FunctionResource
from fastmcp.server.lifespan import lifespan

from mpt_mcp.config import config
from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.gitbook import GitBookClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


class DocumentationState:
    """Documentation cache of the process, and the process that loaded it."""

    def __init__(self) -> None:
        self.cache: DocumentationCache | None = None
        self.pid: int | None = None


documentation_state = DocumentationState()


async def initialize_documentation_cache() -> None:
    """Load the documentation cache once per process, from GitBook when it is configured."""
    # A worker started by fork or spawn is another process and loads its own cache
    if documentation_state.pid == os.getpid():
        return

    documentation_state.cache = await load_documentation_cache()
    documentation_state.pid = os.getpid()


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

    try:
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
        await cache.refresh()
        doc_resources = await cache.list_resources()
    except Exception as error:
        logger.warning("Failed to initialize documentation cache: %s", error)
        return DocumentationCache(gitbook_client=None)

    logger.info(
        "Documentation cache loaded (%s pages); served via docs://{path*} template",
        len(doc_resources),
    )
    logger.info("DOCS CACHE READY — marketplace_docs_list and docs:// resources are available")
    return cache


async def read_documentation_page(cache: DocumentationCache, uri: str) -> str:
    """Return the text of a cached documentation page, or "" when it is not in the cache."""
    page_content = await cache.get_resource(uri)
    return page_content or ""


async def register_documentation_pages(mcp: FastMCP) -> int:
    """
    Register every cached documentation page as its own resource, so clients can list them.

    The docs://{path*} template reads any page; listing the pages needs one resource each.

    Args:
        mcp: Server to add the resources to

    Returns:
        Number of pages registered
    """
    cache = documentation_state.cache
    if not cache or not cache.is_enabled:
        logger.info(
            "Documentation resources: none (set GITBOOK_API_KEY and GITBOOK_SPACE_ID to "
            "enable). docs://{path*} template is still available for reading when configured."
        )
        return 0

    page_count = 0
    for page in await cache.list_resources():
        uri = page.get("uri") or ""
        if not uri.startswith("docs://"):
            continue

        page_metadata = page.get("metadata") or {}
        name = page.get("name") or page_metadata.get("title", uri)
        mcp.add_resource(
            FunctionResource.from_function(
                partial(read_documentation_page, cache, uri),
                uri=uri,
                name=name,
                description=page.get("description") or f"Documentation: {name}",
                mime_type="text/markdown",
            )
        )
        page_count += 1
    logger.info("Registered %s documentation resources for discovery", page_count)
    return page_count


@lifespan
async def documentation_lifespan(server: Any) -> AsyncIterator[dict[str, Any]]:
    """Load the documentation cache when the server starts and list its pages as resources."""
    await initialize_documentation_cache()
    try:
        await register_documentation_pages(server)
    except Exception as error:
        logger.warning("Could not register doc resources for discovery: %s", error)
    yield {}
