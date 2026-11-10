import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from mpt_mcp.config import config
from mpt_mcp.documentation.cache import DocumentationCache
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


def test_get_documentation_store():
    documentation_store = DocumentationStore()
    context = Mock(lifespan_context={DOCUMENTATION_STORE_KEY: documentation_store})

    result = get_documentation_store(context)

    assert result is documentation_store


async def test_get_documentation_cache(cache_loader):
    documentation_store = DocumentationStore()

    result = await get_documentation_cache(documentation_store)

    assert result is cache_loader.return_value
