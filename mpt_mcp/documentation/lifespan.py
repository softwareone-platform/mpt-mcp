from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Any

from fastmcp.resources import FunctionResource
from fastmcp.server.lifespan import lifespan

from mpt_mcp.documentation.store import DOCUMENTATION_STORE_KEY, DocumentationStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastmcp import FastMCP

    from mpt_mcp.documentation.cache import DocumentationCache

logger = logging.getLogger(__name__)


async def read_documentation_page(cache: DocumentationCache, uri: str) -> str:
    """Return the text of a cached documentation page, or "" when it is not in the cache."""
    page_content = await cache.get_resource(uri)
    return page_content or ""


async def register_documentation_pages(mcp: FastMCP, cache: DocumentationCache) -> int:
    """
    Register every cached documentation page as its own resource, so clients can list them.

    The docs://{path*} template reads any page; listing the pages needs one resource each.

    Args:
        mcp: Server to add the resources to
        cache: Loaded documentation cache

    Returns:
        Number of pages registered
    """
    if not cache.is_enabled:
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
    """Load the documentation when the server starts and list its pages as resources."""
    documentation_store = DocumentationStore()
    cache = await documentation_store.get()
    try:
        await register_documentation_pages(server, cache)
    except Exception as error:
        logger.warning("Could not register doc resources for discovery: %s", error)
    yield {DOCUMENTATION_STORE_KEY: documentation_store}


@lifespan
async def documentation_store_lifespan(  # ruff: ignore[unused-async]
    server: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Give the server an empty documentation store: it loads on the first documentation call."""
    yield {DOCUMENTATION_STORE_KEY: DocumentationStore()}
