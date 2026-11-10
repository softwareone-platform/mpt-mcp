from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.documentation import lifespan
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.tools.debug import marketplace_refresh_cache, marketplace_resources_info
from mpt_mcp.tools.spec_store import MarketplaceSpecStore


@pytest.fixture
def api_client():
    return Mock(spec=APIClient, base_url="https://api.test.com")


@pytest.fixture
def spec_store():
    return Mock(spec=MarketplaceSpecStore, get=AsyncMock())


def test_resources_info_reflects_docs_cache(docs_cache_factory, doc_page_factory, monkeypatch):
    cache = docs_cache_factory(resources=[doc_page_factory("docs://readme")])
    monkeypatch.setattr(lifespan.documentation_state, "cache", cache)

    result = (marketplace_resources_info()).model_dump()

    documentation = result["documentation"]
    assert (documentation["enabled"], documentation["total_pages"]) == (True, 1)


async def test_refresh_cache_reloads_spec(api_client, spec_store, spec_factory):
    spec_store.get.return_value = spec_factory(registry={"catalog.products": {}})

    result = await marketplace_refresh_cache(api_client=api_client, spec_store=spec_store)

    assert (result.success, result.endpoints_count) == (True, 1)
    spec_store.get.assert_awaited_once_with("https://api.test.com", force_refresh=True)


async def test_refresh_cache_reports_failed_load(api_client, spec_store):
    spec_store.get.side_effect = OpenAPISpecFetchError("Connection refused")

    with pytest.raises(ToolError, match="Failed to load OpenAPI spec"):
        await marketplace_refresh_cache(api_client=api_client, spec_store=spec_store)
