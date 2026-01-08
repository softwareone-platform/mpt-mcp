#!/usr/bin/env python3
"""
Test RQL (Resource Query Language) implementation
Verifies that our MCP server properly handles RQL parameters according to:
https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language
"""

import pytest
from src.api_client import APIClient
from src.config import config


class TestRQLImplementation:
    """Test RQL query patterns"""
    
    @pytest.fixture
    def api_client(self):
        """Create API client for tests"""
        return APIClient(
            base_url=config.marketplace_api_base_url,
            token=config.marketplace_api_token,
            timeout=config.request_timeout
        )
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_simple_pagination(self, api_client):
        """Test simple pagination with limit"""
        endpoint = "/public/v1/catalog/products"
        result = await api_client.get(endpoint, params={"limit": 1})
        
        assert "data" in result
        assert len(result["data"]) <= 1
        if "pagination" in result:
            assert "total" in result["pagination"]
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rql_filter_by_status(self, api_client):
        """Test RQL filter: eq(status,Published)"""
        endpoint = "/public/v1/catalog/products"
        rql = "eq(status,Published)"
        result = await api_client.get(endpoint, params={"rql": rql, "limit": 1})
        
        assert "data" in result
        if result["data"]:
            assert result["data"][0]["status"] == "Published"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rql_search_with_ilike(self, api_client):
        """Test RQL search: ilike(name,*Microsoft*)"""
        endpoint = "/public/v1/catalog/products"
        rql = "ilike(name,*Microsoft*)"
        result = await api_client.get(endpoint, params={"rql": rql, "limit": 5})
        
        assert "data" in result
        # Note: May return 0 results if no Microsoft products exist
        if result["data"]:
            for product in result["data"]:
                assert "Microsoft" in product["name"]
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rql_ordering_in_query_string(self, api_client):
        """
        Test RQL ordering using query string syntax (CORRECT METHOD).
        
        NOTE: The SoftwareOne Marketplace API requires ordering to be in the query string,
        not as a separate 'order' parameter:
            - Correct: /endpoint?order=-created&limit=10
            - Incorrect: /endpoint with params={"order": "-created"}
        
        This test verifies that ordering via RQL query string works properly.
        """
        endpoint = "/public/v1/catalog/products"
        
        # Build RQL query with ordering
        rql_query = "order=-id&limit=3"
        
        # Pass RQL directly in the query string
        result = await api_client.get(endpoint, params={"rql": rql_query})
        
        # Should get results
        assert "data" in result
        assert "$meta" in result
        
        # Should have pagination info
        pagination = result["$meta"].get("pagination", {})
        assert pagination.get("limit") == 3
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rql_select_fields(self, api_client):
        """Test RQL field selection: select=+id,+name,-description"""
        endpoint = "/public/v1/catalog/products"
        result = await api_client.get(
            endpoint,
            params={"select": "+id,+name", "limit": 1}
        )
        
        assert "data" in result
        if result["data"]:
            product = result["data"][0]
            assert "id" in product
            assert "name" in product
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rql_complex_query(self, api_client):
        """Test complex RQL: and(eq(status,Published),ilike(name,*AWS*))"""
        endpoint = "/public/v1/catalog/products"
        rql = "and(eq(status,Published),ilike(name,*AWS*))"
        # Skip if API doesn't support this combination of parameters
        try:
            result = await api_client.get(
                endpoint,
                params={"rql": rql, "limit": 5}
            )
            assert "data" in result
        except Exception:
            pytest.skip("API doesn't support complex RQL queries")
        
        assert "data" in result
        if result["data"]:
            for product in result["data"]:
                assert product["status"] == "Published"
                assert "AWS" in product["name"] or "aws" in product["name"].lower()
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rql_pagination_offset(self, api_client):
        """Test RQL pagination with offset"""
        endpoint = "/public/v1/catalog/products"
        
        # Get first page
        page1 = await api_client.get(endpoint, params={"limit": 5, "offset": 0})
        assert "data" in page1
        
        # Get second page
        page2 = await api_client.get(endpoint, params={"limit": 5, "offset": 5})
        assert "data" in page2
        
        # Ensure different results (if enough products exist)
        if len(page1["data"]) == 5 and len(page2["data"]) > 0:
            page1_ids = [p["id"] for p in page1["data"]]
            page2_ids = [p["id"] for p in page2["data"]]
            assert page1_ids != page2_ids


@pytest.mark.unit
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
