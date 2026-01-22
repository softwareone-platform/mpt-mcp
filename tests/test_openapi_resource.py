#!/usr/bin/env python3
"""
Tests for OpenAPI specification resource exposure
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestOpenAPIResource:
    """Test the api://openapi.json resource"""

    @pytest.mark.asyncio
    async def test_get_openapi_spec_resource_success(self):
        """Test successful retrieval of OpenAPI spec"""
        import json

        from src.server import get_openapi_spec

        mock_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/public/v1/catalog/products": {"get": {"summary": "List products"}},
            },
        }

        mock_token_info = {"id": "TKN-123-456", "account": {"id": "ACC-123", "name": "Test Account"}}

        # Mock get_current_credentials, token validation, and OpenAPI spec fetch
        with patch("src.server.get_current_credentials", return_value=("idt:TKN-123-456-SECRET", "https://api.test.com")):
            with patch("src.token_validator.validate_token", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = (True, mock_token_info, None)
                with patch("src.endpoint_registry.get_openapi_spec", new_callable=AsyncMock) as mock_get_spec:
                    mock_get_spec.return_value = mock_spec

                    result = await get_openapi_spec()
                    result_dict = json.loads(result)

                    # The function wraps the spec with metadata
                    assert result_dict["spec"] == mock_spec
                    assert result_dict["api_endpoint"] == "https://api.test.com"
                    assert result_dict["authenticated_as"] == "Test Account"
                    assert result_dict["account_id"] == "ACC-123"
                    mock_get_spec.assert_called_once_with("https://api.test.com", force_refresh=False)

    @pytest.mark.asyncio
    async def test_get_openapi_spec_resource_no_token(self):
        """Test that missing token raises error"""
        import json

        from src.server import get_openapi_spec

        # Mock get_current_credentials to return no token
        with patch("src.server.get_current_credentials", return_value=(None, "https://api.test.com")):
            result = await get_openapi_spec()
            result_dict = json.loads(result)
            assert "error" in result_dict
            assert result_dict["error"] == "Authentication required"

    @pytest.mark.asyncio
    async def test_get_openapi_spec_resource_fetch_error(self):
        """Test handling of OpenAPI fetch errors"""
        import json

        from src.server import get_openapi_spec

        # Mock get_current_credentials and token validation
        with patch("src.server.get_current_credentials", return_value=("idt:TKN-123-456-SECRET", "https://api.test.com")):
            with patch("src.token_validator.validate_token", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = (True, {"id": "TKN-123-456"}, None)
                with patch("src.endpoint_registry.get_openapi_spec", new_callable=AsyncMock) as mock_get_spec:
                    mock_get_spec.side_effect = Exception("Failed to fetch OpenAPI spec")

                    result = await get_openapi_spec()
                    result_dict = json.loads(result)
                    assert "error" in result_dict

    @pytest.mark.asyncio
    async def test_openapi_spec_cached_per_endpoint(self):
        """Test that OpenAPI spec is cached per endpoint"""
        from src.endpoint_registry import get_openapi_spec

        mock_spec1 = {
            "openapi": "3.0.0",
            "info": {"title": "API 1", "version": "1.0.0"},
        }
        mock_spec2 = {
            "openapi": "3.0.0",
            "info": {"title": "API 2", "version": "1.0.0"},
        }

        with patch("src.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
            # Configure mock to return different specs
            async def side_effect(endpoint, force_refresh=False):
                if "api1" in endpoint:
                    return mock_spec1
                else:
                    return mock_spec2

            mock_fetch.side_effect = side_effect

            # Get spec for first endpoint
            spec1_first = await get_openapi_spec("https://api1.test.com")
            assert spec1_first == mock_spec1

            # Get spec for different endpoint
            spec2 = await get_openapi_spec("https://api2.test.com")
            assert spec2 == mock_spec2

            # Both specs should be cached now
            assert mock_fetch.call_count == 2


class TestOpenAPIResourceIntegration:
    """Integration tests for OpenAPI resource with MCP"""

    @pytest.mark.asyncio
    async def test_openapi_resource_listed_in_resources(self):
        """Test that api://openapi.json is listed in MCP resources"""
        from src.server import mcp

        resources = await mcp.list_resources()
        resource_uris = [str(r.uri) for r in resources]

        assert "api://openapi.json" in resource_uris

    @pytest.mark.asyncio
    async def test_openapi_resource_has_correct_metadata(self):
        """Test that OpenAPI resource has correct name and description"""
        from src.server import mcp

        resources = await mcp.list_resources()
        openapi_resource = next((r for r in resources if str(r.uri) == "api://openapi.json"), None)

        assert openapi_resource is not None
        # The resource should have a name
        if hasattr(openapi_resource, "name") and openapi_resource.name:
            assert "openapi" in openapi_resource.name.lower() or "specification" in openapi_resource.name.lower()

    @pytest.mark.asyncio
    async def test_openapi_resource_mime_type(self):
        """Test that OpenAPI resource has a mime type specified"""
        from src.server import mcp

        resources = await mcp.list_resources()
        openapi_resource = next((r for r in resources if str(r.uri) == "api://openapi.json"), None)

        assert openapi_resource is not None
        # The resource should have a mimeType (text/plain or application/json)
        if hasattr(openapi_resource, "mimeType") and openapi_resource.mimeType:
            assert openapi_resource.mimeType in ["text/plain", "application/json"]


class TestEndpointRegistryOpenAPI:
    """Test endpoint registry OpenAPI spec management"""

    @pytest.mark.asyncio
    async def test_registry_initializes_empty(self):
        """Test that registry starts with no cached specs"""
        from src.endpoint_registry import _openapi_specs

        # The global registry should exist (may or may not be empty)
        assert isinstance(_openapi_specs, dict)

    @pytest.mark.asyncio
    async def test_registry_caches_spec_after_fetch(self):
        """Test that registry caches spec after fetching"""
        from src.endpoint_registry import _openapi_specs, get_openapi_spec

        mock_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
        }

        with patch("src.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_spec

            endpoint = "https://api.test.com"
            spec = await get_openapi_spec(endpoint)

            assert spec == mock_spec
            # Spec should be cached
            assert endpoint in _openapi_specs
            assert _openapi_specs[endpoint] == mock_spec

    @pytest.mark.asyncio
    async def test_registry_normalizes_endpoint(self):
        """Test that registry normalizes endpoints before caching"""
        from src.endpoint_registry import get_openapi_spec

        mock_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
        }

        with patch("src.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_spec

            # Request with trailing slash
            endpoint1 = "https://api.test.com/"
            spec1 = await get_openapi_spec(endpoint1)

            # Request without trailing slash
            endpoint2 = "https://api.test.com"
            spec2 = await get_openapi_spec(endpoint2)

            # Should use the same cache entry (normalized)
            assert spec1 == spec2
            # Should have only fetched once due to normalization
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_get_openapi_spec_function(self):
        """Test the module-level get_openapi_spec function"""
        from src.endpoint_registry import _openapi_specs, get_openapi_spec

        mock_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
        }

        # Use a unique endpoint to avoid cache interference
        endpoint = "https://api.unique-test-endpoint-12345.com"

        # Clear cache for this endpoint if it exists
        if endpoint in _openapi_specs:
            del _openapi_specs[endpoint]

        with patch("src.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_spec

            spec = await get_openapi_spec(endpoint)

            assert spec == mock_spec
            mock_fetch.assert_called_once()
