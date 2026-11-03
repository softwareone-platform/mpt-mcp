import json
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp import server_tools
from mpt_mcp.call_context import CallContext
from mpt_mcp.documentation import lifespan


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


async def test_query_next_offset_continues_cut_page(call_context, endpoints_registry, api_client):
    endpoints_registry.return_value = {
        "commerce.orders": {"path": "/public/v1/commerce/orders", "parameters": []}
    }
    api_client.get = AsyncMock(
        return_value={
            "$meta": {"pagination": {"offset": 0, "limit": 100, "total": 500}},
            "data": [{"id": f"ORD-{index}", "notes": "x" * 1000} for index in range(100)],
        }
    )

    result = (
        await server_tools.marketplace_query(
            "commerce.orders", limit=100, call_context=call_context
        )
    ).model_dump(by_alias=True)

    pagination = result["$meta"]["pagination"]
    assert len(result["data"]) < 100
    assert pagination["has_more"] is True
    assert pagination["next_offset"] == len(result["data"])
    assert pagination["returned"] == pagination["next_offset"]
    assert result["$meta"]["truncated"]["suggested_limit"] == len(result["data"])


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


def test_resources_info_reflects_docs_cache(docs_cache_factory, doc_page_factory, monkeypatch):
    cache = docs_cache_factory(resources=[doc_page_factory("docs://readme")])
    monkeypatch.setattr(lifespan, "documentation_cache", cache)

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
