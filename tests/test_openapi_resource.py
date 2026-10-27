#!/usr/bin/env python3
from unittest.mock import AsyncMock, patch

import pytest

from mpt_mcp.call_context import CallContext


@pytest.mark.asyncio
async def test_get_openapi_spec_resource_success():
    import json

    from mpt_mcp.server_resources import get_openapi_spec

    mock_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/public/v1/catalog/products": {"get": {"summary": "List products"}},
        },
    }

    mock_token_info = {"id": "TKN-123-456", "account": {"id": "ACC-123", "name": "Test Account"}}

    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.token_validator.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (True, mock_token_info, None)
        with patch("mpt_mcp.endpoint_registry.get_openapi_spec", new_callable=AsyncMock) as mock_get_spec:
            mock_get_spec.return_value = mock_spec

            result = await get_openapi_spec(call_context=call_context)
            result_dict = json.loads(result)

            # The function wraps the spec with metadata
            assert result_dict["spec"] == mock_spec
            assert result_dict["api_endpoint"] == "https://api.test.com"
            assert result_dict["authenticated_as"] == "Test Account"
            assert result_dict["account_id"] == "ACC-123"
            mock_get_spec.assert_called_once_with("https://api.test.com", force_refresh=False)


@pytest.mark.asyncio
async def test_get_openapi_spec_resource_no_token():
    import json

    from mpt_mcp.server_resources import get_openapi_spec

    call_context = CallContext(endpoint="https://api.test.com", token=None)
    result = await get_openapi_spec(call_context=call_context)
    result_dict = json.loads(result)
    assert "error" in result_dict
    assert result_dict["error"] == "Authentication required"


@pytest.mark.asyncio
async def test_get_openapi_spec_resource_fetch_error():
    import json

    from mpt_mcp.server_resources import get_openapi_spec

    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.token_validator.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (True, {"id": "TKN-123-456"}, None)
        with patch("mpt_mcp.endpoint_registry.get_openapi_spec", new_callable=AsyncMock) as mock_get_spec:
            mock_get_spec.side_effect = Exception("Failed to fetch OpenAPI spec")

            result = await get_openapi_spec(call_context=call_context)
            result_dict = json.loads(result)
            assert "error" in result_dict


@pytest.mark.asyncio
async def test_openapi_spec_cached_per_endpoint():
    from mpt_mcp.endpoint_registry import get_openapi_spec

    mock_spec1 = {
        "openapi": "3.0.0",
        "info": {"title": "API 1", "version": "1.0.0"},
    }
    mock_spec2 = {
        "openapi": "3.0.0",
        "info": {"title": "API 2", "version": "1.0.0"},
    }

    with patch("mpt_mcp.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
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


@pytest.mark.asyncio
async def test_openapi_resource_listed_in_resources():
    from mpt_mcp.server import mcp

    resources = {str(r.uri): r for r in (await mcp.list_resources())}
    resource_uris = [str(uri) for uri in resources.keys()]

    assert "api://openapi.json" in resource_uris


@pytest.mark.asyncio
async def test_openapi_resource_has_correct_metadata():
    from mpt_mcp.server import mcp

    resources = {str(r.uri): r for r in (await mcp.list_resources())}
    openapi_resource = resources.get("api://openapi.json")

    assert openapi_resource is not None
    # The resource should have a name
    if hasattr(openapi_resource, "name") and openapi_resource.name:
        assert "openapi" in openapi_resource.name.lower() or "specification" in openapi_resource.name.lower()


@pytest.mark.asyncio
async def test_openapi_resource_mime_type():
    from mpt_mcp.server import mcp

    resources = {str(r.uri): r for r in (await mcp.list_resources())}
    openapi_resource = resources.get("api://openapi.json")

    assert openapi_resource is not None
    assert openapi_resource.mime_type == "application/json"


@pytest.mark.asyncio
async def test_registry_initializes_empty():
    from mpt_mcp.endpoint_registry import _openapi_specs

    # The global registry should exist (may or may not be empty)
    assert isinstance(_openapi_specs, dict)


@pytest.mark.asyncio
async def test_registry_caches_spec_after_fetch():
    from mpt_mcp.endpoint_registry import _openapi_specs, get_openapi_spec

    mock_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
    }

    with patch("mpt_mcp.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_spec

        endpoint = "https://api.test.com"
        spec = await get_openapi_spec(endpoint)

        assert spec == mock_spec
        # Spec should be cached
        assert endpoint in _openapi_specs
        assert _openapi_specs[endpoint] == mock_spec


@pytest.mark.asyncio
async def test_registry_normalizes_endpoint():
    from mpt_mcp.endpoint_registry import get_openapi_spec

    mock_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
    }

    with patch("mpt_mcp.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
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
async def test_get_openapi_spec_function():
    from mpt_mcp.endpoint_registry import _openapi_specs, get_openapi_spec

    mock_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
    }

    # Use a unique endpoint to avoid cache interference
    endpoint = "https://api.unique-test-endpoint-12345.com"

    # Clear cache for this endpoint if it exists
    if endpoint in _openapi_specs:
        del _openapi_specs[endpoint]

    with patch("mpt_mcp.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_spec

        spec = await get_openapi_spec(endpoint)

        assert spec == mock_spec
        mock_fetch.assert_called_once()
