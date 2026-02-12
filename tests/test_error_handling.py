"""
Tests for error handling in the MCP server
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest


class TestAuthenticationErrors:
    """Test authentication error handling"""

    @pytest.mark.asyncio
    async def test_missing_authorization_header(self):
        """Test error when X-MPT-Authorization header is missing"""
        from src.server_context import get_client_api_client_http

        # No context vars set - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            await get_client_api_client_http()

        error_message = str(exc_info.value)
        assert "Missing X-MPT-Authorization header" in error_message or "Missing" in error_message

    def test_normalize_endpoint_url(self):
        """Test URL normalization"""
        from src.server_context import normalize_endpoint_url

        assert normalize_endpoint_url("https://api.s1.show/public") == "https://api.s1.show"
        assert normalize_endpoint_url("https://api.s1.show") == "https://api.s1.show"


class TestAPIErrorResponses:
    """Test API error response formatting"""

    @pytest.mark.asyncio
    async def test_401_unauthorized_error(self):
        """Test 401 error handling"""
        from src.api_client import APIClient

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"error": "Invalid credentials"}
            mock_response.text = "Invalid credentials"

            mock_get = AsyncMock()
            mock_get.side_effect = httpx.HTTPStatusError("401 Unauthorized", request=Mock(), response=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            client = APIClient("https://api.test.com", "test_token")

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.get("/products")

            assert exc_info.value.response.status_code == 401

    @pytest.mark.asyncio
    async def test_403_forbidden_error(self):
        """Test 403 error handling"""
        from src.api_client import APIClient

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 403
            mock_response.json.return_value = {"error": "Access denied"}
            mock_response.text = "Access denied"

            mock_get = AsyncMock()
            mock_get.side_effect = httpx.HTTPStatusError("403 Forbidden", request=Mock(), response=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            client = APIClient("https://api.test.com", "test_token")

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.get("/products")

            assert exc_info.value.response.status_code == 403

    @pytest.mark.asyncio
    async def test_404_not_found_error(self):
        """Test 404 error handling"""
        from src.api_client import APIClient

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"error": "Resource not found"}
            mock_response.text = "Resource not found"

            mock_get = AsyncMock()
            mock_get.side_effect = httpx.HTTPStatusError("404 Not Found", request=Mock(), response=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            client = APIClient("https://api.test.com", "test_token")

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.get("/products/invalid-id")

            assert exc_info.value.response.status_code == 404

    @pytest.mark.asyncio
    async def test_429_rate_limit_error(self):
        """Test 429 rate limit error handling"""
        from src.api_client import APIClient

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.json.return_value = {"error": "Rate limit exceeded"}
            mock_response.text = "Rate limit exceeded"

            mock_get = AsyncMock()
            mock_get.side_effect = httpx.HTTPStatusError("429 Too Many Requests", request=Mock(), response=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            client = APIClient("https://api.test.com", "test_token")

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.get("/products")

            assert exc_info.value.response.status_code == 429

    @pytest.mark.asyncio
    async def test_500_server_error(self):
        """Test 500 server error handling"""
        from src.api_client import APIClient

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.json.return_value = {"error": "Internal server error"}
            mock_response.text = "Internal server error"

            mock_get = AsyncMock()
            mock_get.side_effect = httpx.HTTPStatusError("500 Internal Server Error", request=Mock(), response=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            client = APIClient("https://api.test.com", "test_token")

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await client.get("/products")

            assert exc_info.value.response.status_code == 500


class TestErrorMessages:
    """Test that error messages are user-friendly"""

    @pytest.mark.asyncio
    async def test_missing_auth_error_message_is_clear(self):
        """Test that missing auth error message is clear and actionable"""
        from src.server_context import get_client_api_client_http

        with pytest.raises(ValueError) as exc_info:
            await get_client_api_client_http()

        error_message = str(exc_info.value)

        # Should contain key information
        assert "Missing" in error_message
        assert "X-MPT-Authorization" in error_message
        assert "header" in error_message.lower()
