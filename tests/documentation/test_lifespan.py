from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client, FastMCP

from mpt_mcp.documentation import lifespan
from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.store import DOCUMENTATION_STORE_KEY, DocumentationStore


@pytest.fixture
def docs_page_cache():
    cache = Mock(spec=DocumentationCache, is_enabled=True)
    cache.list_resources = AsyncMock(
        return_value=[
            {"uri": "docs://getting-started", "name": "Getting started"},
            {"uri": "https://example.com/other"},
        ]
    )
    cache.get_resource = AsyncMock(return_value="# Getting started")
    return cache


async def test_register_pages_of_disabled_cache():
    disabled_cache = Mock(spec=DocumentationCache, is_enabled=False)

    result = await lifespan.register_documentation_pages(FastMCP("test"), disabled_cache)

    assert result == 0


async def test_register_documentation_pages(docs_page_cache):
    mcp = FastMCP("test")

    result = await lifespan.register_documentation_pages(mcp, docs_page_cache)

    assert result == 1
    async with Client(mcp) as client:
        page = await client.read_resource("docs://getting-started")
    assert page[0].text == "# Getting started"


async def test_docs_lifespan_lists_pages(docs_page_cache, monkeypatch):
    monkeypatch.setattr(
        "mpt_mcp.documentation.store.load_documentation_cache",
        AsyncMock(return_value=docs_page_cache),
    )
    mcp = FastMCP("test")

    async with lifespan.documentation_lifespan(mcp) as lifespan_context:
        result = lifespan_context[DOCUMENTATION_STORE_KEY].cache

    assert result is docs_page_cache
    assert [str(resource.uri) for resource in await mcp.list_resources()] == [
        "docs://getting-started"
    ]


async def test_docs_store_lifespan_does_not_load():
    async with lifespan.documentation_store_lifespan(FastMCP("test")) as lifespan_context:
        result = lifespan_context[DOCUMENTATION_STORE_KEY]

    assert isinstance(result, DocumentationStore)
    assert result.cache is None
