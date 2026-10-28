#!/usr/bin/env python3
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.call_context import CallContext


@pytest.fixture
def call_context():
    return CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")


@pytest.mark.asyncio
async def test_unknown_resource_suggests_similar(call_context):
    from mpt_mcp.server import marketplace_query

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

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
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


@pytest.mark.asyncio
async def test_unknown_resource_shows_categories(call_context):
    from mpt_mcp.server import marketplace_query

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

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
            mock_get_registry.return_value = mock_registry
            mock_client = Mock()
            mock_client.base_url = "https://api.test.com"
            mock_get_client.return_value = mock_client

            result = await marketplace_query("invalid.resource", call_context=call_context)

            assert "available_categories" in result
            assert "catalog" in result["available_categories"]
            assert "commerce" in result["available_categories"]


@pytest.mark.asyncio
async def test_missing_path_params_shows_example(call_context):
    from mpt_mcp.server import marketplace_query

    mock_registry = {
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [{"name": "id", "in": "path", "required": True}],
        }
    }

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
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


@pytest.mark.asyncio
async def test_path_params_error_includes_realistic_values(call_context):
    from mpt_mcp.server import marketplace_query

    mock_registry = {
        "commerce.orders.by_id": {
            "path": "/public/v1/commerce/orders/{orderId}",
            "summary": "Order by ID",
            "parameters": [{"name": "orderId", "in": "path", "required": True}],
        }
    }

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
            mock_get_registry.return_value = mock_registry
            mock_client = Mock()
            mock_client.base_url = "https://api.test.com"
            mock_get_client.return_value = mock_client

            result = await marketplace_query("commerce.orders.by_id", call_context=call_context)

            # Should use realistic example value
            assert "ORD-" in result["example"]  # Realistic order ID format


@pytest.mark.asyncio
async def test_resource_info_shows_children(call_context):
    from mpt_mcp.server import marketplace_resource_info

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

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
            mock_get_registry.return_value = mock_registry
            mock_client = Mock()
            mock_client.base_url = "https://api.test.com"
            mock_get_client.return_value = mock_client

            result = await marketplace_resource_info("catalog.products", call_context=call_context)

            # Should include child resources
            assert "related_resources" in result
            assert "children" in result["related_resources"]
            child_resources = [r["resource"] for r in result["related_resources"]["children"]]
            assert "catalog.products.by_id" in child_resources


@pytest.mark.asyncio
async def test_resource_info_shows_parent(call_context):
    from mpt_mcp.server import marketplace_resource_info

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

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
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


@pytest.mark.asyncio
async def test_resource_info_shows_multiple_examples(call_context):
    from mpt_mcp.server import marketplace_resource_info

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

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
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


@pytest.mark.asyncio
async def test_resource_info_shows_filtering_tips(call_context):
    from mpt_mcp.server import marketplace_resource_info

    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Active", "Completed"]}}
            ],
        }
    }

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
            mock_get_registry.return_value = mock_registry
            mock_client = Mock()
            mock_client.base_url = "https://api.test.com"
            mock_get_client.return_value = mock_client

            result = await marketplace_resource_info("commerce.orders", call_context=call_context)

            # Should include filtering tips
            assert "filtering_tips" in result
            assert "status" in result["filtering_tips"]


@pytest.mark.asyncio
async def test_api_error_includes_status_code(call_context):
    from mpt_mcp.server import marketplace_query

    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        }
    }

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
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
            assert result["status_code"] == 400
            assert "api_error_details" in result
            assert "Invalid RQL" in result["api_error_details"]["message"]


@pytest.mark.asyncio
async def test_api_error_includes_request_url(call_context):
    from mpt_mcp.server import marketplace_query

    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        }
    }

    with patch(
        "mpt_mcp.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as mock_get_registry:
        with patch.object(
            CallContext, "create_api_client", new_callable=AsyncMock
        ) as mock_get_client:
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
