from __future__ import annotations

import logging
import os
from functools import partial
from typing import TYPE_CHECKING, Any

from fastmcp.resources import FunctionResource
from fastmcp.server.lifespan import lifespan

from mpt_mcp.config import config
from mpt_mcp.documentation_cache import DocumentationCache
from mpt_mcp.gitbook_client import GitBookClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

documentation_cache: DocumentationCache | None = None
_docs_cache_initialized: bool = False
_docs_cache_init_pid: int | None = None


async def initialize_documentation_cache() -> None:
    """Create the documentation cache once per process, from GitBook when it is configured."""
    global documentation_cache, _docs_cache_initialized, _docs_cache_init_pid
    current_pid = os.getpid()
    # Re-init whenever we're in a different process (worker after fork/spawn, or first run). Ensures
    # worker has its own cache.
    if _docs_cache_init_pid != current_pid:
        _docs_cache_initialized = False
        documentation_cache = None
        _docs_cache_init_pid = None
    if _docs_cache_initialized:
        return

    logger.info("Loading documentation cache...")
    if config.gitbook_api_key and config.gitbook_space_id:
        try:
            gitbook_client = GitBookClient(
                api_key=config.gitbook_api_key,
                space_id=config.gitbook_space_id,
                base_url=config.gitbook_api_base_url,
                max_concurrent_requests=config.gitbook_max_concurrent_requests,
            )
            if await gitbook_client.validate_credentials():
                documentation_cache = DocumentationCache(
                    gitbook_client=gitbook_client,
                    refresh_interval_hours=config.gitbook_cache_refresh_hours,
                    public_url=config.gitbook_public_url,
                )
                await documentation_cache.refresh()
                doc_resources = await documentation_cache.list_resources()
                logger.info(
                    "Documentation cache loaded (%s pages); served via docs://{path*} template",
                    len(doc_resources),
                )
                logger.info("Documentation cache initialized")
                logger.info(
                    "DOCS CACHE READY — marketplace_docs_list and docs:// resources are available"
                )
            else:
                logger.warning("GitBook credentials invalid, documentation cache disabled")
                documentation_cache = DocumentationCache(gitbook_client=None)
        except Exception as error:
            logger.warning("Failed to initialize documentation cache: %s", error)
            documentation_cache = DocumentationCache(gitbook_client=None)
    else:
        has_key = bool(config.gitbook_api_key)
        has_space = bool(config.gitbook_space_id)
        logger.info(
            "GitBook not configured, documentation cache disabled (GITBOOK_API_KEY=%s, "
            "GITBOOK_SPACE_ID=%s).",
            "set" if has_key else "missing",
            "set" if has_space else "missing",
        )
        documentation_cache = DocumentationCache(gitbook_client=None)
    _docs_cache_initialized = True
    _docs_cache_init_pid = os.getpid()


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
    if not documentation_cache or not documentation_cache.is_enabled:
        logger.info(
            "Documentation resources: none (set GITBOOK_API_KEY and GITBOOK_SPACE_ID to "
            "enable). docs://{path*} template is still available for reading when configured."
        )
        return 0

    page_count = 0
    for page in await documentation_cache.list_resources():
        uri = page.get("uri") or ""
        if not uri.startswith("docs://"):
            continue

        page_metadata = page.get("metadata") or {}
        name = page.get("name") or page_metadata.get("title", uri)
        mcp.add_resource(
            FunctionResource.from_function(
                partial(read_documentation_page, documentation_cache, uri),
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
