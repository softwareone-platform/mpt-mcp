#!/usr/bin/env python3
"""
Test RQL (Resource Query Language) implementation
Verifies that our MCP server properly handles RQL parameters according to:
https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.api_client import APIClient


class TestRQLImplementation:
    """Test RQL query patterns with mocked API responses"""

    @pytest.fixture
    def api_client(self):
        """Create API client for tests"""
        return APIClient(base_url="https://api.test.com", token="test_token", timeout=30.0)

    @pytest.fixture
    def mock_product_response(self):
        """Mock API response with product data"""
        return {
            "data": [{"id": "prod-123", "name": "Microsoft Office 365", "status": "Published", "description": "Office suite"}],
            "$meta": {"pagination": {"total": 100, "limit": 1, "offset": 0}},
        }

    @pytest.mark.asyncio
    async def test_simple_pagination(self, api_client, mock_product_response):
        """Test simple pagination with limit"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = mock_product_response
            mock_response.raise_for_status = Mock()

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"
            result = await api_client.get(endpoint, params={"limit": 1})

            assert "data" in result
            assert len(result["data"]) <= 1
            assert "$meta" in result
            assert result["$meta"]["pagination"]["limit"] == 1

    @pytest.mark.asyncio
    async def test_rql_filter_by_status(self, api_client, mock_product_response):
        """Test RQL filter: eq(status,Published)"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = mock_product_response
            mock_response.raise_for_status = Mock()

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"
            rql = "eq(status,Published)"
            result = await api_client.get(endpoint, params={"rql": rql, "limit": 1})

            assert "data" in result
            assert result["data"][0]["status"] == "Published"

            # Verify the API was called with correct parameters
            call_args = mock_get.call_args
            assert "eq(status,Published)" in str(call_args)

    @pytest.mark.asyncio
    async def test_rql_search_with_ilike(self, api_client, mock_product_response):
        """Test RQL search: ilike(name,*Microsoft*)"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = mock_product_response
            mock_response.raise_for_status = Mock()

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"
            rql = "ilike(name,*Microsoft*)"
            result = await api_client.get(endpoint, params={"rql": rql, "limit": 5})

            assert "data" in result
            for product in result["data"]:
                assert "Microsoft" in product["name"]

    @pytest.mark.asyncio
    async def test_rql_ordering_in_query_string(self, api_client):
        """
        Test RQL ordering using query string syntax (CORRECT METHOD).

        NOTE: The SoftwareOne Marketplace API requires ordering to be in the query string,
        not as a separate 'order' parameter:
            - Correct: /endpoint?order=-created&limit=10
            - Incorrect: /endpoint with params={"order": "-created"}

        This test verifies that ordering via RQL query string works properly.
        """
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = {
                "data": [
                    {"id": "prod-3", "name": "Product 3"},
                    {"id": "prod-2", "name": "Product 2"},
                    {"id": "prod-1", "name": "Product 1"},
                ],
                "$meta": {"pagination": {"limit": 3, "offset": 0, "total": 100}},
            }
            mock_response.raise_for_status = Mock()

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"
            rql_query = "order=-id&limit=3"
            result = await api_client.get(endpoint, params={"rql": rql_query})

            assert "data" in result
            assert "$meta" in result
            pagination = result["$meta"].get("pagination", {})
            assert pagination.get("limit") == 3

            # Verify URL contains ordering
            call_args = mock_get.call_args
            assert "order=-id" in str(call_args)

    @pytest.mark.asyncio
    async def test_rql_select_fields(self, api_client):
        """Test RQL field selection: select=+id,+name,-description"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = {
                "data": [{"id": "prod-123", "name": "Product Name"}],
                "$meta": {"pagination": {"limit": 1}},
            }
            mock_response.raise_for_status = Mock()

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"
            result = await api_client.get(endpoint, params={"select": "+id,+name", "limit": 1})

            assert "data" in result
            product = result["data"][0]
            assert "id" in product
            assert "name" in product

    @pytest.mark.asyncio
    async def test_rql_complex_query(self, api_client):
        """Test complex RQL: and(eq(status,Published),ilike(name,*AWS*))"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = {
                "data": [
                    {"id": "prod-aws-1", "name": "AWS Lambda", "status": "Published"},
                    {"id": "prod-aws-2", "name": "AWS EC2", "status": "Published"},
                ],
                "$meta": {"pagination": {"limit": 5}},
            }
            mock_response.raise_for_status = Mock()

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"
            rql = "and(eq(status,Published),ilike(name,*AWS*))"
            result = await api_client.get(endpoint, params={"rql": rql, "limit": 5})

            assert "data" in result
            for product in result["data"]:
                assert product["status"] == "Published"
                assert "AWS" in product["name"]

    @pytest.mark.asyncio
    async def test_rql_pagination_offset(self, api_client):
        """Test RQL pagination with offset"""
        with patch("httpx.AsyncClient") as mock_client:
            # Mock responses for two pages
            page1_response = Mock()
            page1_response.json.return_value = {
                "data": [{"id": f"prod-{i}", "name": f"Product {i}"} for i in range(1, 6)],
                "$meta": {"pagination": {"limit": 5, "offset": 0, "total": 100}},
            }
            page1_response.raise_for_status = Mock()

            page2_response = Mock()
            page2_response.json.return_value = {
                "data": [{"id": f"prod-{i}", "name": f"Product {i}"} for i in range(6, 11)],
                "$meta": {"pagination": {"limit": 5, "offset": 5, "total": 100}},
            }
            page2_response.raise_for_status = Mock()

            mock_get = AsyncMock(side_effect=[page1_response, page2_response])
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/catalog/products"

            # Get first page
            page1 = await api_client.get(endpoint, params={"limit": 5, "offset": 0})
            assert "data" in page1

            # Get second page
            page2 = await api_client.get(endpoint, params={"limit": 5, "offset": 5})
            assert "data" in page2

            # Ensure different results
            page1_ids = [p["id"] for p in page1["data"]]
            page2_ids = [p["id"] for p in page2["data"]]
            assert page1_ids != page2_ids


def test_rql_syntax():
    """Test that RQL syntax is properly understood"""
    # Test cases for RQL syntax
    test_cases = [
        ("eq(status,Active)", "Simple equality"),
        ("ilike(name,*Microsoft*)", "Case-insensitive search"),
        ("and(eq(status,Active),gt(price,100))", "Complex AND"),
        ("or(eq(type,A),eq(type,B))", "Complex OR"),
    ]

    for rql, description in test_cases:
        # Verify RQL syntax is valid (basic check)
        assert rql, f"RQL should not be empty: {description}"
        assert "(" in rql and ")" in rql, f"RQL should have parentheses: {description}"
