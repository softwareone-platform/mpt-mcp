import json
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp import server_docs, server_tools
from mpt_mcp.call_context import CallContext


@pytest.fixture
def call_context():
    return CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")


@pytest.fixture
def endpoints_registry():
    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as get_endpoints_registry:
        yield get_endpoints_registry


@pytest.fixture
def api_client():
    client = Mock()
    client.base_url = "https://api.test.com"
    with patch.object(
        CallContext, "create_api_client", new_callable=AsyncMock, return_value=client
    ):
        yield client


async def test_query_without_credentials_fails(call_context, endpoints_registry):
    with (
        patch.object(
            CallContext,
            "create_api_client",
            new_callable=AsyncMock,
            side_effect=ValueError("Missing X-MPT-Authorization header"),
        ),
        pytest.raises(ToolError, match="Missing X-MPT-Authorization header") as error,
    ):
        await server_tools.marketplace_query("catalog.products", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details == {"hint": server_tools.AUTH_HEADER_HINT}


async def test_query_wraps_plain_values(call_context, endpoints_registry, api_client):
    endpoints_registry.return_value = {
        "commerce.orders.render": {"path": "/public/v1/commerce/orders/render", "parameters": []}
    }
    api_client.get = AsyncMock(return_value="<h1>Order</h1>")

    result = (
        await server_tools.marketplace_query("commerce.orders.render", call_context=call_context)
    ).model_dump()

    assert result == {"result": "<h1>Order</h1>"}


async def test_unknown_resource_suggests_similar(call_context, endpoints_registry, api_client):
    # Mock the endpoint registry with some sample resources
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [],
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [],
        },
        "accounts.buyers": {
            "path": "/public/v1/accounts/buyers",
            "summary": "Buyers",
            "parameters": [],
        },
    }

    endpoints_registry.return_value = mock_registry

    with pytest.raises(ToolError, match=r"Unknown resource: 'catalog\.product'") as error:
        await server_tools.marketplace_query("catalog.product", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert "catalog.products" in details["did_you_mean"]


async def test_unknown_resource_shows_categories(call_context, endpoints_registry, api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [],
        },
    }

    endpoints_registry.return_value = mock_registry

    with pytest.raises(ToolError) as error:
        await server_tools.marketplace_query("invalid.resource", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert sorted(details["available_categories"]) == ["catalog", "commerce"]


async def test_missing_path_params_shows_example(call_context, endpoints_registry, api_client):
    mock_registry = {
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [{"name": "id", "in": "path", "required": True}],
        }
    }

    endpoints_registry.return_value = mock_registry

    with pytest.raises(ToolError, match="requires path parameters: id") as error:
        await server_tools.marketplace_query("catalog.products.by_id", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["example"] == (
        "marketplace_query(resource='catalog.products.by_id', "
        "path_params={'id': 'PRD-1234-5678'}, limit=10)"
    )
    assert "hint" in details


async def test_path_params_error_has_realistic_values(call_context, endpoints_registry, api_client):
    mock_registry = {
        "commerce.orders.by_id": {
            "path": "/public/v1/commerce/orders/{orderId}",
            "summary": "Order by ID",
            "parameters": [{"name": "orderId", "in": "path", "required": True}],
        }
    }

    endpoints_registry.return_value = mock_registry

    with pytest.raises(ToolError) as error:
        await server_tools.marketplace_query("commerce.orders.by_id", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert "'orderId': 'ORD-1234-5678-9012'" in details["example"]


async def test_resource_info_shows_children(call_context, endpoints_registry, api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [],
        },
        "catalog.products.by_id.items": {
            "path": "/public/v1/catalog/products/{id}/items",
            "summary": "Product items",
            "parameters": [],
        },
    }

    endpoints_registry.return_value = mock_registry

    result = (
        await server_tools.marketplace_resource_info("catalog.products", call_context=call_context)
    ).model_dump()

    # Should include child resources
    assert "related_resources" in result
    assert "children" in result["related_resources"]
    child_resources = [resource["resource"] for resource in result["related_resources"]["children"]]
    assert "catalog.products.by_id" in child_resources


async def test_resource_info_shows_parent(call_context, endpoints_registry, api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [],
        },
    }

    endpoints_registry.return_value = mock_registry

    result = (
        await server_tools.marketplace_resource_info(
            "catalog.products.by_id", call_context=call_context
        )
    ).model_dump()

    # Should include parent resource
    assert "related_resources" in result
    assert "parent" in result["related_resources"]
    assert result["related_resources"]["parent"]["resource"] == "catalog.products"


async def test_resource_info_shows_multiple_examples(call_context, endpoints_registry, api_client):
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [
                {
                    "name": "status",
                    "in": "query",
                    "schema": {"type": "string", "enum": ["Active", "Completed", "Cancelled"]},
                }
            ],
        }
    }

    endpoints_registry.return_value = mock_registry

    result = (
        await server_tools.marketplace_resource_info("commerce.orders", call_context=call_context)
    ).model_dump()

    # Should include multiple examples
    assert "example_queries" in result
    assert len(result["example_queries"]) > 1

    # Should include example with enum filter
    example_strings = " ".join(result["example_queries"])
    assert "Active" in example_strings or "Completed" in example_strings


async def test_resource_info_shows_filtering_tips(call_context, endpoints_registry, api_client):
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Active", "Completed"]}}
            ],
        }
    }

    endpoints_registry.return_value = mock_registry

    result = (
        await server_tools.marketplace_resource_info("commerce.orders", call_context=call_context)
    ).model_dump()

    # Should include filtering tips
    assert "filtering_tips" in result
    assert "status" in result["filtering_tips"]


async def test_api_error_includes_status_code(call_context, endpoints_registry, api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        }
    }

    endpoints_registry.return_value = mock_registry

    # Mock API client to raise 400 error
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"message": "Invalid RQL", "field": "rql"}
    mock_response.text = "Bad Request"

    mock_request = Mock()
    mock_request.url = "https://api.test.com/public/v1/catalog/products"

    http_error = httpx.HTTPStatusError(
        "400 Bad Request", request=mock_request, response=mock_response
    )

    api_client.get = AsyncMock(side_effect=http_error)

    with pytest.raises(ToolError, match="400 Bad Request") as error:
        await server_tools.marketplace_query("catalog.products", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["status_code"] == HTTPStatus.BAD_REQUEST
    assert details["api_error_details"]["message"] == "Invalid RQL"


async def test_api_error_includes_request_url(call_context, endpoints_registry, api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        }
    }

    endpoints_registry.return_value = mock_registry

    # Mock API error
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.json.side_effect = Exception("Not JSON")
    mock_response.text = "Not found"

    mock_request = Mock()
    mock_request.url = "https://api.test.com/public/v1/catalog/products"

    http_error = httpx.HTTPStatusError(
        "404 Not Found", request=mock_request, response=mock_response
    )

    api_client.get = AsyncMock(side_effect=http_error)

    with pytest.raises(ToolError) as error:
        await server_tools.marketplace_query("catalog.products", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["request_url"] == "https://api.test.com/public/v1/catalog/products"


async def test_docs_list_exposes_browser_url_and_note():
    mock_resources = [
        {
            "uri": "docs://help-and-support/contact-support",
            "name": "Contact Support",
            "description": "Documentation page: Contact Support",
            "mimeType": "text/markdown",
            "metadata": {
                "id": "7qHvpiUID0CAu2h8cXUr",
                "path": "help-and-support/contact-support",
                "title": "Contact Support",
                "browser_url": "https://docs.example.com/help-and-support/contact-support",
            },
        },
    ]
    mock_cache = Mock()
    mock_cache.is_enabled = True
    mock_cache.list_resources = AsyncMock(return_value=mock_resources)

    with (
        patch("mpt_mcp.server_docs.documentation_cache", mock_cache),
        patch("mpt_mcp.server_docs.initialize_documentation_cache", AsyncMock()),
    ):
        result = (await server_tools.marketplace_docs_list(search="contact support")).model_dump()

    assert result["total"] == 1
    assert len(result["resources"]) == 1
    assert (
        result["resources"][0]["browser_url"]
        == "https://docs.example.com/help-and-support/contact-support"
    )
    assert "Prefer showing users the browser_url" in result["usage"]
    assert "do not show internal uri or id" in result["usage"]


async def test_docs_list_without_browser_url_metadata():
    mock_resources = [
        {
            "uri": "docs://some/page",
            "name": "Some Page",
            "description": "A page",
            "mimeType": "text/markdown",
            "metadata": {"id": "abc", "path": "some/page", "title": "Some Page"},
        },
    ]
    mock_cache = Mock()
    mock_cache.is_enabled = True
    mock_cache.list_resources = AsyncMock(return_value=mock_resources)

    with (
        patch("mpt_mcp.server_docs.documentation_cache", mock_cache),
        patch("mpt_mcp.server_docs.initialize_documentation_cache", AsyncMock()),
    ):
        result = (await server_tools.marketplace_docs_list(search="some")).model_dump()

    assert result["total"] == 1
    assert "browser_url" not in result["resources"][0]
    assert "Prefer showing users the browser_url" in result["usage"]


@pytest.fixture
def doc_page():
    def _doc_page(uri, browser_url=None):
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

    return _doc_page


@pytest.fixture
def docs_cache(monkeypatch):
    def _docs_cache(resources=(), index=None, content_by_uri=None):
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
            server_docs.documentation_cache = cache

        # Tools must read the cache that initialize_documentation_cache sets, not a stale import
        monkeypatch.setattr(server_docs, "documentation_cache", None)
        monkeypatch.setattr(
            server_docs, "initialize_documentation_cache", AsyncMock(side_effect=install_cache)
        )
        return cache

    return _docs_cache


async def test_docs_index_without_cache_fails(monkeypatch):
    monkeypatch.setattr(server_docs, "initialize_documentation_cache", AsyncMock())
    monkeypatch.setattr(server_docs, "documentation_cache", None)

    with pytest.raises(ToolError, match="Documentation cache is not available"):
        await server_tools.marketplace_docs_index()


async def test_docs_index_returns_cache_index(docs_cache):
    index = {
        "total_pages": 1,
        "sections": [{"name": "readme", "total_pages": 1, "subsections": []}],
    }
    docs_cache(resources=[{"uri": "docs://readme", "metadata": {}}], index=index)

    result = (await server_tools.marketplace_docs_index()).model_dump()

    assert result == index


async def test_docs_list_includes_browser_url_and_usage(docs_cache, doc_page):
    docs_cache(
        resources=[
            doc_page(
                "docs://help-and-support/contact-support",
                browser_url="https://example.test/contact-support",
            )
        ]
    )

    result = (await server_tools.marketplace_docs_list(search="contact", limit=100)).model_dump()

    assert (result["total"], result["resources"][0]["browser_url"]) == (
        1,
        "https://example.test/contact-support",
    )
    assert "Prefer showing users the browser_url" in result["usage"]


async def test_marketplace_docs_list_tip_when_limited(docs_cache, doc_page):
    resources = [doc_page(f"docs://p/{index}") for index in range(10)]
    docs_cache(resources=resources)

    result = (await server_tools.marketplace_docs_list(limit=5)).model_dump()

    assert "tip" in result


async def test_docs_list_uses_live_docs_cache(docs_cache, doc_page):
    docs_cache(resources=[doc_page("docs://readme")])

    result = (await server_tools.marketplace_docs_list(limit=5)).model_dump()

    first_uri = result["resources"][0]["uri"]
    assert (result["total"], first_uri) == (1, "docs://readme")


async def test_docs_read_returns_text_and_count(docs_cache):
    docs_cache(
        content_by_uri={"docs://help-and-support/contact-support": "# Contact\n\nHello from docs."}
    )

    result = (
        await server_tools.marketplace_docs_read(uri="docs://help-and-support/contact-support")
    ).model_dump()

    assert result == {"text": "# Contact\n\nHello from docs.", "count": 1}


async def test_docs_read_not_found_fails(docs_cache):
    docs_cache()

    with pytest.raises(ToolError, match="Documentation page not found: docs://missing/page"):
        await server_tools.marketplace_docs_read(uri="docs://missing/page")


def test_resources_info_reflects_docs_cache(docs_cache, doc_page, monkeypatch):
    cache = docs_cache(resources=[doc_page("docs://readme")])
    monkeypatch.setattr(server_docs, "documentation_cache", cache)

    result = (server_tools.marketplace_resources_info()).model_dump()

    documentation = result["documentation"]
    assert (documentation["enabled"], documentation["total_pages"]) == (True, 1)


async def test_refresh_cache_reloads_registry(call_context, endpoints_registry, api_client):
    endpoints_registry.return_value = {"catalog.products": {}}

    result = (await server_tools.marketplace_refresh_cache(call_context=call_context)).model_dump()

    assert (result["success"], result["endpoints_count"]) == (True, 1)
    endpoints_registry.assert_called_once_with("https://api.test.com", force_refresh=True)


async def test_refresh_cache_reports_failed_load(call_context, endpoints_registry, api_client):
    endpoints_registry.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(ToolError, match="Failed to load OpenAPI spec"):
        await server_tools.marketplace_refresh_cache(call_context=call_context)
