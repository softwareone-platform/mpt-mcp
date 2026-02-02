#!/usr/bin/env python3
"""
Test default limit feature.

Verifies that the MCP server automatically applies limit=10 when:
1. No limit is specified (None)
2. Limit is explicitly set to a value (should be respected)
3. Limit is set to 0 (should be respected as intentional)

This prevents huge responses (platform default is 1000, which is too large for most use cases).
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.mcp_tools import execute_marketplace_query


class TestDefaultLimit:
    """Test automatic default limit application"""

    @pytest.fixture
    def api_client(self):
        """Create a mock API client"""
        client = Mock()
        client.get = AsyncMock()
        return client

    @pytest.fixture
    def endpoints_registry(self):
        """Create a mock endpoints registry"""
        return {
            "catalog.products": {
                "path": "/public/v1/catalog/products",
                "method": "GET",
            }
        }

    @pytest.fixture
    def mock_api_response(self):
        """Mock API response"""
        return {
            "data": [{"id": f"prod-{i}", "name": f"Product {i}"} for i in range(1, 11)],
            "$meta": {"pagination": {"total": 100, "limit": 10, "offset": 0}},
        }

    @pytest.mark.asyncio
    async def test_applies_default_limit_when_none(self, api_client, mock_api_response, endpoints_registry):
        """Test that limit=10 is applied when limit is None"""
        api_client.get.return_value = mock_api_response

        result = await execute_marketplace_query(
            resource="catalog.products",
            rql="",
            limit=None,  # No limit specified
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )

        # Verify API was called with limit=10
        call_args = api_client.get.call_args
        assert call_args is not None, "API client should have been called"

        # Check that limit=10 was passed in params
        params = call_args.kwargs.get("params", {})
        assert "limit" in params, "Limit parameter should be present"
        assert params["limit"] == 10, f"Expected limit=10, got limit={params.get('limit')}"

        # Verify result
        assert "data" in result
        assert "$meta" in result

    @pytest.mark.asyncio
    async def test_respects_explicit_limit(self, api_client, mock_api_response, endpoints_registry):
        """Test that explicit limit values are respected"""
        api_client.get.return_value = mock_api_response

        # Test with limit=50
        result = await execute_marketplace_query(
            resource="catalog.products",
            rql="",
            limit=50,  # Explicit limit
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )

        # Verify API was called with limit=50 (not default 10)
        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["limit"] == 50, f"Expected limit=50, got limit={params.get('limit')}"

        # Verify result
        assert "data" in result

    @pytest.mark.asyncio
    async def test_respects_limit_zero(self, api_client, mock_api_response, endpoints_registry):
        """Test that limit=0 is respected (might be intentional)"""
        api_client.get.return_value = mock_api_response

        result = await execute_marketplace_query(
            resource="catalog.products",
            rql="",
            limit=0,  # Explicit limit=0
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )

        # Verify API was called with limit=0 (not default 10)
        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["limit"] == 0, f"Expected limit=0, got limit={params.get('limit')}"

    @pytest.mark.asyncio
    async def test_default_limit_with_rql(self, api_client, mock_api_response, endpoints_registry):
        """Test that default limit works with RQL queries"""
        api_client.get.return_value = mock_api_response

        result = await execute_marketplace_query(
            resource="catalog.products",
            rql="eq(status,Published)",  # RQL query
            limit=None,  # No limit specified
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )

        # Verify API was called with both RQL and limit=10
        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["rql"] == "eq(status,Published)", "RQL should be preserved"
        assert params["limit"] == 10, "Default limit should be applied"

    @pytest.mark.asyncio
    async def test_default_limit_with_other_params(self, api_client, mock_api_response, endpoints_registry):
        """Test that default limit works with other parameters (select, order, etc.)"""
        api_client.get.return_value = mock_api_response

        result = await execute_marketplace_query(
            resource="catalog.products",
            rql="",
            limit=None,  # No limit specified
            offset=None,
            page=None,
            select="+id,+name",  # Select parameter
            order="-created",  # Order parameter
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )

        # Verify API was called with all parameters including default limit
        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["select"] == "+id,+name", "Select should be preserved"
        assert params["order"] == "-created", "Order should be preserved"
        assert params["limit"] == 10, "Default limit should be applied"

    @pytest.mark.asyncio
    async def test_default_limit_logs_message(self, api_client, mock_api_response, endpoints_registry):
        """Test that applying default limit logs an informative message"""
        log_messages = []

        def log_fn(message: str):
            log_messages.append(message)

        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="catalog.products",
            rql="",
            limit=None,  # No limit specified
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=log_fn,
        )

        # Check that log message about default limit was generated
        log_text = " ".join(log_messages)
        assert "default limit=10" in log_text.lower() or "applied default" in log_text.lower(), f"Expected log message about default limit, got: {log_messages}"
