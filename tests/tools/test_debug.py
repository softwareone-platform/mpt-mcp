import httpx
import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.documentation import lifespan
from mpt_mcp.tools.debug import marketplace_refresh_cache, marketplace_resources_info


def test_resources_info_reflects_docs_cache(docs_cache_factory, doc_page_factory, monkeypatch):
    cache = docs_cache_factory(resources=[doc_page_factory("docs://readme")])
    monkeypatch.setattr(lifespan, "documentation_cache", cache)

    result = (marketplace_resources_info()).model_dump()

    documentation = result["documentation"]
    assert (documentation["enabled"], documentation["total_pages"]) == (True, 1)


async def test_refresh_cache_reloads_registry(call_context, registry_loader, patched_api_client):
    registry_loader.return_value = {"catalog.products": {}}

    result = (await marketplace_refresh_cache(call_context=call_context)).model_dump()

    assert (result["success"], result["endpoints_count"]) == (True, 1)
    registry_loader.assert_called_once_with("https://api.test.com", force_refresh=True)


async def test_refresh_cache_reports_failed_load(call_context, registry_loader, patched_api_client):
    registry_loader.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(ToolError, match="Failed to load OpenAPI spec"):
        await marketplace_refresh_cache(call_context=call_context)
