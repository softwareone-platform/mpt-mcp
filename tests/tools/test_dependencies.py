import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.auth.call_context import CallContext
from mpt_mcp.auth.token_validator import TokenValidator
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.tools.dependencies import get_api_client, get_marketplace_spec, get_spec_store
from mpt_mcp.tools.results import AUTH_HEADER_HINT
from mpt_mcp.tools.spec_store import SPEC_STORE_KEY, MarketplaceSpecStore


@pytest.fixture
def api_client():
    return Mock(spec=APIClient, base_url="https://api.test.com")


@pytest.fixture
def spec_store():
    return Mock(spec=MarketplaceSpecStore, get=AsyncMock())


async def test_get_api_client(call_context, patched_api_client):
    result = await get_api_client(call_context, TokenValidator())

    assert result is patched_api_client


async def test_get_api_client_without_credentials_fails(call_context):
    with (
        patch.object(
            CallContext,
            "create_api_client",
            new_callable=AsyncMock,
            side_effect=ValueError("Missing X-MPT-Authorization header"),
        ),
        pytest.raises(ToolError, match="Missing X-MPT-Authorization header") as error,
    ):
        await get_api_client(call_context, TokenValidator())

    _, error_details = str(error.value).split("\n", 1)
    assert json.loads(error_details) == {"hint": AUTH_HEADER_HINT}


def test_get_spec_store():
    spec_store = MarketplaceSpecStore()
    context = Mock(lifespan_context={SPEC_STORE_KEY: spec_store})

    result = get_spec_store(context)

    assert result is spec_store


async def test_get_marketplace_spec(api_client, spec_store, spec_factory):
    spec_store.get.return_value = spec_factory()

    result = await get_marketplace_spec(api_client, spec_store)

    assert result is spec_store.get.return_value
    spec_store.get.assert_awaited_once_with("https://api.test.com")


async def test_get_marketplace_spec_load_fails(api_client, spec_store):
    spec_store.get.side_effect = OpenAPISpecFetchError("Connection refused")

    with pytest.raises(ToolError, match="Failed to load OpenAPI spec for your endpoint") as error:
        await get_marketplace_spec(api_client, spec_store)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["api_endpoint"] == "https://api.test.com"
    assert details["details"] == "Connection refused"
