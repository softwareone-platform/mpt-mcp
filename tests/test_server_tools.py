from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp import server_docs, server_tools
from mpt_mcp.call_context import CallContext


@pytest.fixture
def call_context():
    return CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")


async def test_unknown_resource_suggests_similar(call_context, http_tools):
    marketplace_query = http_tools["marketplace_query"]
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

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        # Try to query "catalog.product" (typo - missing 's')
        result = await marketplace_query("catalog.product", call_context=call_context)

        # Should return error with suggestions
        assert "error" in result
        assert "catalog.product" in result["error"]
        assert "did_you_mean" in result
        assert "catalog.products" in result["did_you_mean"]


async def test_unknown_resource_shows_categories(call_context, http_tools):
    marketplace_query = http_tools["marketplace_query"]
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

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        result = await marketplace_query("invalid.resource", call_context=call_context)

        assert "available_categories" in result
        assert "catalog" in result["available_categories"]
        assert "commerce" in result["available_categories"]


async def test_missing_path_params_shows_example(call_context, http_tools):
    marketplace_query = http_tools["marketplace_query"]
    mock_registry = {
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [{"name": "id", "in": "path", "required": True}],
        }
    }

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        # Query without providing path_params
        result = await marketplace_query("catalog.products.by_id", call_context=call_context)

        # Should include helpful error
        assert "error" in result
        assert "path parameters" in result["error"].lower()
        assert "example" in result
        assert "marketplace_query" in result["example"]
        assert "path_params" in result["example"]
        assert "hint" in result


async def test_path_params_error_has_realistic_values(call_context, http_tools):
    marketplace_query = http_tools["marketplace_query"]
    mock_registry = {
        "commerce.orders.by_id": {
            "path": "/public/v1/commerce/orders/{orderId}",
            "summary": "Order by ID",
            "parameters": [{"name": "orderId", "in": "path", "required": True}],
        }
    }

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        result = await marketplace_query("commerce.orders.by_id", call_context=call_context)

        # Should use realistic example value
        assert "ORD-" in result["example"]  # Realistic order ID format


async def test_resource_info_shows_children(call_context, http_tools):
    marketplace_resource_info = http_tools["marketplace_resource_info"]
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

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        result = await marketplace_resource_info("catalog.products", call_context=call_context)

        # Should include child resources
        assert "related_resources" in result
        assert "children" in result["related_resources"]
        child_resources = [
            resource["resource"] for resource in result["related_resources"]["children"]
        ]
        assert "catalog.products.by_id" in child_resources


async def test_resource_info_shows_parent(call_context, http_tools):
    marketplace_resource_info = http_tools["marketplace_resource_info"]
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

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        result = await marketplace_resource_info(
            "catalog.products.by_id", call_context=call_context
        )

        # Should include parent resource
        assert "related_resources" in result
        assert "parent" in result["related_resources"]
        assert result["related_resources"]["parent"]["resource"] == "catalog.products"


async def test_resource_info_shows_multiple_examples(call_context, http_tools):
    marketplace_resource_info = http_tools["marketplace_resource_info"]
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

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        result = await marketplace_resource_info("commerce.orders", call_context=call_context)

        # Should include multiple examples
        assert "example_queries" in result
        assert len(result["example_queries"]) > 1

        # Should include example with enum filter
        example_strings = " ".join(result["example_queries"])
        assert "Active" in example_strings or "Completed" in example_strings


async def test_resource_info_shows_filtering_tips(call_context, http_tools):
    marketplace_resource_info = http_tools["marketplace_resource_info"]
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Active", "Completed"]}}
            ],
        }
    }

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"
        mock_get_client.return_value = mock_client

        result = await marketplace_resource_info("commerce.orders", call_context=call_context)

        # Should include filtering tips
        assert "filtering_tips" in result
        assert "status" in result["filtering_tips"]


async def test_api_error_includes_status_code(call_context, http_tools):
    marketplace_query = http_tools["marketplace_query"]
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        }
    }

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"

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

        mock_client.get = AsyncMock(side_effect=http_error)
        mock_get_client.return_value = mock_client

        result = await marketplace_query("catalog.products", call_context=call_context)

        # Should preserve API error details
        assert "error" in result
        assert "status_code" in result
        assert result["status_code"] == HTTPStatus.BAD_REQUEST
        assert "api_error_details" in result
        assert "Invalid RQL" in result["api_error_details"]["message"]


async def test_api_error_includes_request_url(call_context, http_tools):
    marketplace_query = http_tools["marketplace_query"]
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        }
    }

    with (
        patch(
            "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
        ) as mock_get_registry,
        patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as mock_get_client,
    ):
        mock_get_registry.return_value = mock_registry
        mock_client = Mock()
        mock_client.base_url = "https://api.test.com"

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

        mock_client.get = AsyncMock(side_effect=http_error)
        mock_get_client.return_value = mock_client

        result = await marketplace_query("catalog.products", call_context=call_context)

        # Should include request URL
        assert "request_url" in result
        assert "api.test.com" in result["request_url"]


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
        result = await server_tools.marketplace_docs_list(search="contact support")

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
        result = await server_tools.marketplace_docs_list(search="some")

    assert result["total"] == 1
    assert "browser_url" not in result["resources"][0]
    assert "Prefer showing users the browser_url" in result["usage"]


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


@pytest.fixture
def http_tools():
    fake_mcp = Mock()
    server_tools.register_http_tools(fake_mcp)
    return {
        call.args[0].__name__: call.args[0] for call in fake_mcp.tool.return_value.call_args_list
    }


async def test_docs_index_returns_cache_index(docs_cache, http_tools):
    index = {
        "total_pages": 1,
        "sections": [{"name": "readme", "total_pages": 1, "subsections": []}],
    }
    docs_cache(resources=[{"uri": "docs://readme", "metadata": {}}], index=index)

    result = await http_tools["marketplace_docs_index"]()

    assert result == index


async def test_docs_list_includes_browser_url_and_usage(docs_cache):
    docs_cache(
        resources=[
            {
                "uri": "docs://help-and-support/contact-support",
                "name": "Contact Support",
                "metadata": {"browser_url": "https://example.test/contact-support"},
            }
        ]
    )

    result = await server_tools.marketplace_docs_list(search="contact", limit=100)

    assert (result["total"], result["resources"][0]["browser_url"]) == (
        1,
        "https://example.test/contact-support",
    )
    assert "Prefer showing users the browser_url" in result["usage"]


async def test_marketplace_docs_list_tip_when_limited(docs_cache):
    docs_cache(resources=[{"uri": f"docs://p/{index}", "metadata": {}} for index in range(10)])

    result = await server_tools.marketplace_docs_list(limit=5)

    assert "tip" in result


async def test_docs_list_uses_live_docs_cache(docs_cache):
    docs_cache(resources=[{"uri": "docs://readme", "metadata": {}}])

    result = await server_tools.marketplace_docs_list(limit=5)

    assert (result["total"], result["resources"][0]["uri"]) == (1, "docs://readme")


async def test_docs_read_returns_text_and_count(docs_cache, http_tools):
    docs_cache(
        content_by_uri={"docs://help-and-support/contact-support": "# Contact\n\nHello from docs."}
    )

    result = await http_tools["marketplace_docs_read"](
        uri="docs://help-and-support/contact-support"
    )

    assert result == {"text": "# Contact\n\nHello from docs.", "count": 1}


async def test_docs_read_not_found_returns_zero_count(docs_cache, http_tools):
    docs_cache()

    result = await http_tools["marketplace_docs_read"](uri="docs://missing/page")

    assert (result["count"], "not found" in result["text"].lower()) == (0, True)


async def test_resources_info_reflects_docs_cache(docs_cache, http_tools, monkeypatch):
    cache = docs_cache(resources=[{"uri": "docs://readme", "metadata": {}}])
    monkeypatch.setattr(server_docs, "documentation_cache", cache)

    result = await http_tools["marketplace_resources_info"]()

    assert (result["documentation"]["enabled"], result["documentation"]["total_pages"]) == (True, 1)
