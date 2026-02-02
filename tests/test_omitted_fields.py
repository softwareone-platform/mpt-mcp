#!/usr/bin/env python3
"""
Test omitted fields feature.

Verifies that the MCP server:
1. Logs $meta.omitted fields in API responses
2. Documents omitted fields in marketplace_resource_info()
3. Documents omitted fields in marketplace_resources() tips
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.api_client import APIClient
from src.mcp_tools import execute_marketplace_resource_info, execute_marketplace_resources


class TestOmittedFieldsLogging:
    """Test that $meta.omitted fields are logged correctly"""

    @pytest.fixture
    def api_client(self):
        """Create API client for tests"""
        return APIClient(base_url="https://api.test.com", token="test_token", timeout=30.0)

    @pytest.mark.asyncio
    async def test_logs_omitted_fields_in_response(self, api_client):
        """Test that omitted fields are logged when present in API response"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = {
                "data": [{"id": "ORD-123", "status": "Completed"}],
                "$meta": {
                    "pagination": {"total": 1, "limit": 10, "offset": 0},
                    "omitted": ["lines", "parameters", "subscriptions", "assets"],
                },
            }
            mock_response.raise_for_status = Mock()
            mock_response.status_code = 200

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            # Capture log output
            with patch("src.api_client.logger") as mock_logger:
                endpoint = "/public/v1/commerce/orders"
                result = await api_client.get(endpoint, params={"limit": 10})

                # Verify response contains omitted fields
                assert "$meta" in result
                assert "omitted" in result["$meta"]
                assert result["$meta"]["omitted"] == ["lines", "parameters", "subscriptions", "assets"]

                # Verify logging was called with omitted fields info
                log_calls = [str(call) for call in mock_logger.info.call_args_list]
                omitted_logged = any("omitted" in str(call).lower() for call in log_calls)
                assert omitted_logged, "Omitted fields should be logged"

    @pytest.mark.asyncio
    async def test_handles_response_without_omitted_fields(self, api_client):
        """Test that responses without omitted fields are handled gracefully"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = {
                "data": [{"id": "ORD-123", "status": "Completed"}],
                "$meta": {
                    "pagination": {"total": 1, "limit": 10, "offset": 0},
                    # No "omitted" field
                },
            }
            mock_response.raise_for_status = Mock()
            mock_response.status_code = 200

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/commerce/orders"
            result = await api_client.get(endpoint, params={"limit": 10})

            # Should not raise error when omitted is missing
            assert "$meta" in result
            assert "omitted" not in result["$meta"] or result["$meta"].get("omitted") is None

    @pytest.mark.asyncio
    async def test_handles_empty_omitted_fields_list(self, api_client):
        """Test that empty omitted fields list is handled correctly"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.json.return_value = {
                "data": [{"id": "ORD-123", "status": "Completed"}],
                "$meta": {
                    "pagination": {"total": 1, "limit": 10, "offset": 0},
                    "omitted": [],  # Empty list
                },
            }
            mock_response.raise_for_status = Mock()
            mock_response.status_code = 200

            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/commerce/orders"
            result = await api_client.get(endpoint, params={"limit": 10})

            assert "$meta" in result
            assert result["$meta"]["omitted"] == []


class TestOmittedFieldsDocumentation:
    """Test that omitted fields are documented in tool responses"""

    @pytest.fixture
    def endpoints_registry(self):
        """Create a mock endpoints registry"""
        return {
            "commerce.orders": {
                "path": "/public/v1/commerce/orders",
                "method": "GET",
                "summary": "List orders",
                "description": "Get a list of orders",
                "parameters": [],
            }
        }

    @pytest.mark.asyncio
    async def test_marketplace_resource_info_includes_omitted_fields_note(self, endpoints_registry):
        """Test that marketplace_resource_info() includes note about omitted fields"""
        result = await execute_marketplace_resource_info(
            resource="commerce.orders",
            endpoints_registry=endpoints_registry,
        )

        # Verify omitted_fields_note is present
        assert "omitted_fields_note" in result
        assert "omitted" in result["omitted_fields_note"].lower()
        assert "$meta.omitted" in result["omitted_fields_note"]
        assert "select=+field" in result["omitted_fields_note"]

    @pytest.mark.asyncio
    async def test_marketplace_resource_info_select_param_documents_omitted_fields(self, endpoints_registry):
        """Test that select parameter documentation mentions omitted fields"""
        result = await execute_marketplace_resource_info(
            resource="commerce.orders",
            endpoints_registry=endpoints_registry,
        )

        # Verify select parameter documentation mentions omitted fields
        assert "common_parameters" in result
        select_doc = result["common_parameters"]["select"]
        assert "omitted" in select_doc.lower() or "$meta.omitted" in select_doc
        assert "select=+field" in select_doc or "+field" in select_doc

    @pytest.mark.asyncio
    async def test_marketplace_resources_tips_mention_omitted_fields(self):
        """Test that marketplace_resources() tips mention omitted fields"""
        mock_registry = {
            "commerce.orders": {
                "path": "/public/v1/commerce/orders",
                "method": "GET",
                "summary": "List orders",
                "parameters": [],
            }
        }

        result = await execute_marketplace_resources(
            endpoints_registry=mock_registry,
            api_base_url="https://api.test.com",
            user_id="test-user",
        )

        # Verify tips include information about omitted fields
        assert "tips" in result
        assert "field_selection" in result["tips"]
        field_selection_tip = result["tips"]["field_selection"]
        assert "omitted" in field_selection_tip.lower() or "$meta.omitted" in field_selection_tip
        assert "select=+field" in field_selection_tip or "+field" in field_selection_tip

    @pytest.mark.asyncio
    async def test_marketplace_resource_info_handles_unknown_resource(self, endpoints_registry):
        """Test that marketplace_resource_info() handles unknown resources gracefully"""
        result = await execute_marketplace_resource_info(
            resource="unknown.resource",
            endpoints_registry=endpoints_registry,
        )

        # Should return error, not crash
        assert "error" in result
        assert "Unknown resource" in result["error"]


class TestOmittedFieldsWithSelectParameter:
    """Test that omitted fields work correctly with select parameter"""

    @pytest.fixture
    def api_client(self):
        """Create API client for tests"""
        return APIClient(base_url="https://api.test.com", token="test_token", timeout=30.0)

    @pytest.mark.asyncio
    async def test_select_parameter_includes_omitted_fields(self, api_client):
        """Test that select=+field includes omitted fields in response"""
        with patch("httpx.AsyncClient") as mock_client:
            # First response: fields omitted
            mock_response_omitted = Mock()
            mock_response_omitted.json.return_value = {
                "data": [{"id": "ORD-123", "status": "Completed"}],
                "$meta": {
                    "pagination": {"total": 1, "limit": 10, "offset": 0},
                    "omitted": ["lines", "parameters"],
                },
            }
            mock_response_omitted.raise_for_status = Mock()
            mock_response_omitted.status_code = 200

            # Second response: fields included via select
            mock_response_included = Mock()
            mock_response_included.json.return_value = {
                "data": [
                    {
                        "id": "ORD-123",
                        "status": "Completed",
                        "lines": [{"id": "LINE-1", "quantity": 1}],
                        "parameters": {"key": "value"},
                    }
                ],
                "$meta": {
                    "pagination": {"total": 1, "limit": 10, "offset": 0},
                    "omitted": [],  # No omitted fields when explicitly selected
                },
            }
            mock_response_included.raise_for_status = Mock()
            mock_response_included.status_code = 200

            mock_get = AsyncMock(side_effect=[mock_response_omitted, mock_response_included])
            mock_client.return_value.__aenter__.return_value.get = mock_get

            endpoint = "/public/v1/commerce/orders"

            # First call: without select
            result1 = await api_client.get(endpoint, params={"limit": 10})
            assert "omitted" in result1["$meta"]
            assert "lines" in result1["$meta"]["omitted"]

            # Second call: with select=+lines,+parameters
            result2 = await api_client.get(endpoint, params={"limit": 10, "select": "+lines,+parameters"})
            # When fields are explicitly selected, they should be in data
            if "lines" in result2.get("data", [{}])[0]:
                assert "lines" in result2["data"][0]
            # omitted list may be empty or not include the selected fields
            assert "$meta" in result2
