from unittest.mock import AsyncMock, Mock

import pytest

from mpt_mcp.documentation.cache import DocumentationCache


@pytest.fixture
def doc_page_factory():
    def factory(uri, browser_url=None):
        metadata = {"id": "7qHvpiUID0CAu2h8cXUr", "path": uri.removeprefix("docs://"), "title": uri}
        if browser_url:
            metadata["browser_url"] = browser_url
        return {
            "uri": uri,
            "name": uri,
            "description": f"Documentation page: {uri}",
            "mimeType": "text/markdown",
            "metadata": metadata,
        }

    return factory


@pytest.fixture
def docs_cache_factory(monkeypatch):
    def factory(resources=(), index=None, content_by_uri=None):
        cache = Mock(
            spec=DocumentationCache,
            is_enabled=True,
            list_resources=AsyncMock(return_value=list(resources)),
        )
        cache.get_documentation_index = AsyncMock(
            return_value=index or {"total_pages": 0, "sections": []}
        )
        cache.get_resource = AsyncMock(side_effect=(content_by_uri or {}).get)
        cache.get_cache_info.return_value = {
            "resource_count": len(resources),
            "last_refresh": "now",
            "enabled": True,
        }

        # Servers in tests load this cache from their documentation store
        monkeypatch.setattr(
            "mpt_mcp.documentation.store.load_documentation_cache", AsyncMock(return_value=cache)
        )
        return cache

    return factory
