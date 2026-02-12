#!/usr/bin/env python3
"""
Test UX improvements: better error messages, resource discovery, and API error preservation
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest


class TestDidYouMeanSuggestions:
    """Test 'did you mean' suggestions for unknown resources"""

    @pytest.mark.asyncio
    async def test_unknown_resource_suggests_similar(self):
        """Test that unknown resource errors suggest similar resources"""
        from src.server import marketplace_query

        # Mock the endpoint registry with some sample resources
        mock_registry = {
            "catalog.products": {"path": "/public/v1/catalog/products", "summary": "Products", "parameters": []},
            "catalog.products.by_id": {
                "path": "/public/v1/catalog/products/{id}",
                "summary": "Product by ID",
                "parameters": [],
            },
            "commerce.orders": {"path": "/public/v1/commerce/orders", "summary": "Orders", "parameters": []},
            "accounts.buyers": {"path": "/public/v1/accounts/buyers", "summary": "Buyers", "parameters": []},
        }

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                # Try to query "catalog.product" (typo - missing 's')
                result = await marketplace_query("catalog.product")

                # Should return error with suggestions
                assert "error" in result
                assert "catalog.product" in result["error"]
                assert "did_you_mean" in result
                assert "catalog.products" in result["did_you_mean"]

    @pytest.mark.asyncio
    async def test_unknown_resource_shows_categories(self):
        """Test that unknown resource errors show available categories"""
        from src.server import marketplace_query

        mock_registry = {
            "catalog.products": {"path": "/public/v1/catalog/products", "summary": "Products", "parameters": []},
            "commerce.orders": {"path": "/public/v1/commerce/orders", "summary": "Orders", "parameters": []},
        }

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                result = await marketplace_query("invalid.resource")

                assert "available_categories" in result
                assert "catalog" in result["available_categories"]
                assert "commerce" in result["available_categories"]


class TestEnhancedPathParamsErrors:
    """Test enhanced path parameter error messages"""

    @pytest.mark.asyncio
    async def test_missing_path_params_shows_example(self):
        """Test that missing path params error includes realistic example"""
        from src.server import marketplace_query

        mock_registry = {
            "catalog.products.by_id": {
                "path": "/public/v1/catalog/products/{id}",
                "summary": "Product by ID",
                "parameters": [{"name": "id", "in": "path", "required": True}],
            }
        }

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                # Query without providing path_params
                result = await marketplace_query("catalog.products.by_id")

                # Should include helpful error
                assert "error" in result
                assert "path parameters" in result["error"].lower()
                assert "example" in result
                assert "marketplace_query" in result["example"]
                assert "path_params" in result["example"]
                assert "hint" in result

    @pytest.mark.asyncio
    async def test_path_params_error_includes_realistic_values(self):
        """Test that path params examples use realistic IDs"""
        from src.server import marketplace_query

        mock_registry = {
            "commerce.orders.by_id": {
                "path": "/public/v1/commerce/orders/{orderId}",
                "summary": "Order by ID",
                "parameters": [{"name": "orderId", "in": "path", "required": True}],
            }
        }

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                result = await marketplace_query("commerce.orders.by_id")

                # Should use realistic example value
                assert "ORD-" in result["example"]  # Realistic order ID format


class TestRelatedResourcesDiscovery:
    """Test related resources discovery (parent, children, siblings)"""

    @pytest.mark.asyncio
    async def test_resource_info_shows_children(self):
        """Test that resource_info shows child resources"""
        from src.server import marketplace_resource_info

        mock_registry = {
            "catalog.products": {"path": "/public/v1/catalog/products", "summary": "Products", "parameters": []},
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

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                result = await marketplace_resource_info("catalog.products")

                # Should include child resources
                assert "related_resources" in result
                assert "children" in result["related_resources"]
                child_resources = [r["resource"] for r in result["related_resources"]["children"]]
                assert "catalog.products.by_id" in child_resources

    @pytest.mark.asyncio
    async def test_resource_info_shows_parent(self):
        """Test that resource_info shows parent resource"""
        from src.server import marketplace_resource_info

        mock_registry = {
            "catalog.products": {"path": "/public/v1/catalog/products", "summary": "Products", "parameters": []},
            "catalog.products.by_id": {
                "path": "/public/v1/catalog/products/{id}",
                "summary": "Product by ID",
                "parameters": [],
            },
        }

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                result = await marketplace_resource_info("catalog.products.by_id")

                # Should include parent resource
                assert "related_resources" in result
                assert "parent" in result["related_resources"]
                assert result["related_resources"]["parent"]["resource"] == "catalog.products"


class TestMultipleQueryExamples:
    """Test that resource_info provides multiple helpful query examples"""

    @pytest.mark.asyncio
    async def test_resource_info_shows_multiple_examples(self):
        """Test that resources with enums show multiple examples"""
        from src.server import marketplace_resource_info

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

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                result = await marketplace_resource_info("commerce.orders")

                # Should include multiple examples
                assert "example_queries" in result
                assert len(result["example_queries"]) > 1

                # Should include example with enum filter
                example_strings = " ".join(result["example_queries"])
                assert "Active" in example_strings or "Completed" in example_strings

    @pytest.mark.asyncio
    async def test_resource_info_shows_filtering_tips(self):
        """Test that resources with enums show filtering tips"""
        from src.server import marketplace_resource_info

        mock_registry = {
            "commerce.orders": {
                "path": "/public/v1/commerce/orders",
                "summary": "Orders",
                "parameters": [{"name": "status", "in": "query", "schema": {"enum": ["Active", "Completed"]}}],
            }
        }

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
                mock_get_registry.return_value = mock_registry
                mock_client = Mock()
                mock_client.base_url = "https://api.test.com"
                mock_get_client.return_value = mock_client

                result = await marketplace_resource_info("commerce.orders")

                # Should include filtering tips
                assert "filtering_tips" in result
                assert "status" in result["filtering_tips"]


class TestAPIErrorDetailsPreservation:
    """Test that API error details are preserved in responses"""

    @pytest.mark.asyncio
    async def test_api_error_includes_status_code(self):
        """Test that HTTP errors include status code"""
        from src.server import marketplace_query

        mock_registry = {"catalog.products": {"path": "/public/v1/catalog/products", "summary": "Products", "parameters": []}}

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
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

                http_error = httpx.HTTPStatusError("400 Bad Request", request=mock_request, response=mock_response)

                mock_client.get = AsyncMock(side_effect=http_error)
                mock_get_client.return_value = mock_client

                result = await marketplace_query("catalog.products")

                # Should preserve API error details
                assert "error" in result
                assert "status_code" in result
                assert result["status_code"] == 400
                assert "api_error_details" in result
                assert "Invalid RQL" in result["api_error_details"]["message"]

    @pytest.mark.asyncio
    async def test_api_error_includes_request_url(self):
        """Test that errors include the full request URL"""
        from src.server import marketplace_query

        mock_registry = {"catalog.products": {"path": "/public/v1/catalog/products", "summary": "Products", "parameters": []}}

        with patch("src.server_tools.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock) as mock_get_registry:
            with patch("src.server_tools.get_client_api_client_http", new_callable=AsyncMock) as mock_get_client:
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

                http_error = httpx.HTTPStatusError("404 Not Found", request=mock_request, response=mock_response)

                mock_client.get = AsyncMock(side_effect=http_error)
                mock_get_client.return_value = mock_client

                result = await marketplace_query("catalog.products")

                # Should include request URL
                assert "request_url" in result
                assert "api.test.com" in result["request_url"]
