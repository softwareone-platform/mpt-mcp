import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import Client

from mpt_mcp import server_docs
from mpt_mcp.call_context import CallContext
from mpt_mcp.server import mcp
from mpt_mcp.server_resources import get_documentation_page, get_openapi_spec


async def test_get_openapi_spec_resource_success():

    mock_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/public/v1/catalog/products": {"get": {"summary": "List products"}},
        },
    }

    mock_token_info = {"id": "TKN-123-456", "account": {"id": "ACC-123", "name": "Test Account"}}

    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.server_resources.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (True, mock_token_info, None)
        with patch(
            "mpt_mcp.endpoint_registry.get_openapi_spec", new_callable=AsyncMock
        ) as mock_get_spec:
            mock_get_spec.return_value = mock_spec

            result = await get_openapi_spec(call_context=call_context)
            result_dict = json.loads(result)

            # The function wraps the spec with metadata
            assert result_dict["spec"] == mock_spec
            assert result_dict["api_endpoint"] == "https://api.test.com"
            assert result_dict["authenticated_as"] == "Test Account"
            assert result_dict["account_id"] == "ACC-123"
            mock_get_spec.assert_called_once_with("https://api.test.com", force_refresh=False)


async def test_get_openapi_spec_resource_no_token():

    call_context = CallContext(endpoint="https://api.test.com", token=None)
    result = await get_openapi_spec(call_context=call_context)
    result_dict = json.loads(result)
    assert "error" in result_dict
    assert result_dict["error"] == "Authentication required"


async def test_get_openapi_spec_resource_fetch_error():

    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.server_resources.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (True, {"id": "TKN-123-456"}, None)
        with patch(
            "mpt_mcp.endpoint_registry.get_openapi_spec", new_callable=AsyncMock
        ) as mock_get_spec:
            mock_get_spec.side_effect = Exception("Failed to fetch OpenAPI spec")

            result = await get_openapi_spec(call_context=call_context)
            result_dict = json.loads(result)
            assert "error" in result_dict


async def test_openapi_resource_listed_in_resources():

    resources = {str(resource.uri): resource for resource in (await mcp.list_resources())}
    resource_uris = [str(uri) for uri in resources]

    assert "api://openapi.json" in resource_uris


async def test_openapi_resource_has_correct_metadata():

    resources = {str(resource.uri): resource for resource in (await mcp.list_resources())}
    openapi_resource = resources.get("api://openapi.json")

    assert openapi_resource is not None
    # The resource should have a name
    if hasattr(openapi_resource, "name") and openapi_resource.name:
        assert (
            "openapi" in openapi_resource.name.lower()
            or "specification" in openapi_resource.name.lower()
        )


async def test_openapi_resource_mime_type():

    resources = {str(resource.uri): resource for resource in (await mcp.list_resources())}
    openapi_resource = resources.get("api://openapi.json")

    assert openapi_resource is not None
    assert openapi_resource.mime_type == "application/json"


@pytest.fixture
def docs_cache(monkeypatch):
    def _docs_cache(content_by_uri):
        cache = Mock(is_enabled=True)
        cache.get_resource = AsyncMock(side_effect=content_by_uri.get)

        def install_cache():
            server_docs.documentation_cache = cache

        # The resource must read the cache that initialize_documentation_cache sets, not a stale
        # import
        monkeypatch.setattr(server_docs, "documentation_cache", None)
        monkeypatch.setattr(
            server_docs, "initialize_documentation_cache", AsyncMock(side_effect=install_cache)
        )
        return cache

    return _docs_cache


async def test_docs_resource_reads_from_live_docs_cache(docs_cache):
    docs_cache({"docs://readme": "# Home\n\nHello"})

    result = await get_documentation_page("readme")

    assert result == "# Home\n\nHello"


async def test_docs_resource_not_found_when_missing(docs_cache):
    docs_cache({})

    result = await get_documentation_page("readme")

    assert result == "Documentation page not found: docs://readme"


async def test_docs_resource_reads_nested_paths(docs_cache):
    docs_cache({"docs://help-and-support/contact-support": "# Contact"})

    async with Client(mcp) as client:
        result = await client.read_resource("docs://help-and-support/contact-support")

    assert result[0].text == "# Contact"
