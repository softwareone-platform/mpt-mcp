import os
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client, FastMCP

from mpt_mcp import server_docs


@pytest.fixture
def gitbook_not_configured(monkeypatch):
    monkeypatch.setattr(server_docs.config, "gitbook_api_key", "")
    monkeypatch.setattr(server_docs.config, "gitbook_space_id", "")


@pytest.mark.usefixtures("gitbook_not_configured")
async def test_init_docs_cache_disabled_without_gitbook():
    await server_docs.initialize_documentation_cache()  # act

    assert server_docs.documentation_cache.is_enabled is False


@pytest.mark.usefixtures("gitbook_not_configured")
async def test_init_docs_cache_again_in_new_process(monkeypatch):
    await server_docs.initialize_documentation_cache()
    stale_cache = Mock()
    monkeypatch.setattr(server_docs, "documentation_cache", stale_cache)
    other_pid = os.getpid() + 1
    monkeypatch.setattr(server_docs.os, "getpid", Mock(return_value=other_pid))

    await server_docs.initialize_documentation_cache()  # act

    assert server_docs.documentation_cache is not stale_cache


async def test_register_documentation_pages(monkeypatch):
    cache = Mock(is_enabled=True)
    cache.list_resources = AsyncMock(
        return_value=[
            {"uri": "docs://getting-started", "name": "Getting started"},
            {"uri": "https://example.com/other"},
        ]
    )
    cache.get_resource = AsyncMock(return_value="# Getting started")
    monkeypatch.setattr(server_docs, "documentation_cache", cache)
    mcp = FastMCP("test")

    result = await server_docs.register_documentation_pages(mcp)

    assert result == 1
    async with Client(mcp) as client:
        page = await client.read_resource("docs://getting-started")
    assert page[0].text == "# Getting started"


@pytest.mark.usefixtures("gitbook_not_configured")
async def test_register_pages_without_gitbook():
    await server_docs.initialize_documentation_cache()

    result = await server_docs.register_documentation_pages(FastMCP("test"))

    assert result == 0
