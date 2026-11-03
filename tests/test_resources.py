import json
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ResourceError

from mpt_mcp.auth.call_context import CallContext
from mpt_mcp.mcp_server import create_mcp_server
from mpt_mcp.resources import get_openapi_spec


@pytest.fixture
def mcp_server():
    return create_mcp_server(transport="stdio")


async def test_get_openapi_spec_resource_success():
    mock_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/public/v1/catalog/products": {"get": {"summary": "List products"}},
        },
    }

    mock_token_info = {"id": "TKN-123-456", "account": {"id": "ACC-123", "name": "Test Account"}}

    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.resources.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (True, mock_token_info, None)
        with patch(
            "mpt_mcp.marketplace.endpoint_registry.get_openapi_spec", new_callable=AsyncMock
        ) as mock_get_spec:
            mock_get_spec.return_value = mock_spec

            result = await get_openapi_spec(call_context=call_context)
            result_dict = json.loads(result)

            assert result_dict["spec"] == mock_spec
            assert result_dict["api_endpoint"] == "https://api.test.com"
            assert result_dict["authenticated_as"] == "Test Account"
            assert result_dict["account_id"] == "ACC-123"
            mock_get_spec.assert_called_once_with("https://api.test.com", force_refresh=False)


async def test_get_openapi_spec_resource_no_token():
    call_context = CallContext(endpoint="https://api.test.com", token=None)

    with pytest.raises(ResourceError, match="Authentication required"):
        await get_openapi_spec(call_context=call_context)


async def test_get_openapi_spec_resource_invalid_token():
    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.resources.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (False, None, "Token expired")

        with pytest.raises(ResourceError, match="Token validation failed: Token expired"):
            await get_openapi_spec(call_context=call_context)


async def test_get_openapi_spec_resource_fetch_error():
    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-123-456-SECRET")
    with patch("mpt_mcp.resources.validate_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (True, {"id": "TKN-123-456"}, None)
        with patch(
            "mpt_mcp.marketplace.endpoint_registry.get_openapi_spec", new_callable=AsyncMock
        ) as mock_get_spec:
            mock_get_spec.side_effect = RuntimeError("Connection refused")

            with pytest.raises(ResourceError, match="Connection refused"):
                await get_openapi_spec(call_context=call_context)


async def test_openapi_resource_error_reaches_client(mcp_server):
    async with Client(mcp_server) as client:
        with pytest.raises(Exception, match="Authentication required"):
            await client.read_resource("api://openapi.json")


async def test_openapi_resource_listed_with_metadata(mcp_server):
    result = {str(resource.uri): resource for resource in await mcp_server.list_resources()}

    assert (result["api://openapi.json"].name, result["api://openapi.json"].mime_type) == (
        "OpenAPI Specification",
        "application/json",
    )
