import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from mpt_mcp.config import config
from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.gitbook import GitBookClient
from mpt_mcp.documentation.store import (
    DOCUMENTATION_STORE_KEY,
    DocumentationStore,
    get_documentation_cache,
    get_documentation_store,
    load_documentation_cache,
)


@pytest.fixture
def cache_loader(monkeypatch):
    loader = AsyncMock(return_value=Mock(spec=DocumentationCache, is_enabled=True))
    monkeypatch.setattr("mpt_mcp.documentation.store.load_documentation_cache", loader)
    return loader


@pytest.fixture
def gitbook_configured(monkeypatch):
    monkeypatch.setattr(config, "gitbook_api_key", "test_api_key")
    monkeypatch.setattr(config, "gitbook_space_id", "test_space_id")


@pytest.fixture
def gitbook_client(monkeypatch):
    client = Mock(spec=GitBookClient)
    client.validate_credentials = AsyncMock(return_value=True)
    client.fetch_space_content = AsyncMock(return_value={"pages": []})
    monkeypatch.setattr("mpt_mcp.documentation.store.GitBookClient", Mock(return_value=client))
    return client


@pytest.fixture
def gitbook_not_configured(monkeypatch):
    monkeypatch.setattr(config, "gitbook_api_key", "")
    monkeypatch.setattr(config, "gitbook_space_id", "")


async def test_get_loads_cache_once(cache_loader):
    documentation_store = DocumentationStore()

    result = await asyncio.gather(documentation_store.get(), documentation_store.get())

    assert result == [documentation_store.cache, documentation_store.cache]
    cache_loader.assert_awaited_once()


@pytest.mark.usefixtures("gitbook_not_configured")
async def test_load_without_gitbook_is_disabled():
    result = await load_documentation_cache()

    assert result.is_enabled is False


@pytest.mark.usefixtures("gitbook_configured")
async def test_load_with_bad_credentials_is_disabled(gitbook_client):
    gitbook_client.validate_credentials.return_value = False

    result = await load_documentation_cache()

    assert result.is_enabled is False


@pytest.mark.usefixtures("gitbook_configured")
async def test_load_with_failed_index_stays_enabled(gitbook_client):
    gitbook_client.fetch_space_content.side_effect = httpx.ConnectError("Connection refused")

    result = await load_documentation_cache()

    assert (result.is_enabled, result.get_cache_info()["has_content"]) == (True, False)


def test_get_documentation_store():
    documentation_store = DocumentationStore()
    context = Mock(lifespan_context={DOCUMENTATION_STORE_KEY: documentation_store})

    result = get_documentation_store(context)

    assert result is documentation_store


async def test_get_documentation_cache(cache_loader):
    documentation_store = DocumentationStore()

    result = await get_documentation_cache(documentation_store)

    assert result is cache_loader.return_value
