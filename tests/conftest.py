from unittest.mock import AsyncMock, Mock

import pytest

from mpt_mcp.documentation import lifespan


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
        cache = Mock(is_enabled=True)
        cache.list_resources = AsyncMock(return_value=list(resources))
        cache.get_documentation_index = AsyncMock(
            return_value=index or {"total_pages": 0, "sections": []}
        )
        cache.get_resource = AsyncMock(side_effect=(content_by_uri or {}).get)
        cache.get_cache_info.return_value = {
            "resource_count": len(resources),
            "last_refresh": "now",
            "enabled": True,
        }

        def install_cache():
            lifespan.documentation_cache = cache

        # Tools must read the cache that initialize_documentation_cache sets, not a stale import
        monkeypatch.setattr(lifespan, "documentation_cache", None)
        monkeypatch.setattr(
            lifespan, "initialize_documentation_cache", AsyncMock(side_effect=install_cache)
        )
        return cache

    return factory
