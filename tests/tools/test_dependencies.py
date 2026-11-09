import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.auth.call_context import CallContext
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.audit_fields import FALLBACK_STATIC_REGEX
from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.marketplace.schemas import OpenAPISpec
from mpt_mcp.tools.dependencies import get_api_client, get_marketplace_spec
from mpt_mcp.tools.results import AUTH_HEADER_HINT
from mpt_mcp.tools.spec import MarketplaceSpec


@pytest.fixture
def api_client():
    return Mock(spec=APIClient, base_url="https://api.test.com")


@pytest.fixture
def registry_loader():
    with patch(
        "mpt_mcp.tools.dependencies.get_endpoints_registry", new_callable=AsyncMock
    ) as get_endpoints_registry:
        yield get_endpoints_registry


@pytest.fixture
def spec_loader():
    with patch(
        "mpt_mcp.tools.dependencies.get_openapi_spec", new_callable=AsyncMock
    ) as get_openapi_spec:
        yield get_openapi_spec


async def test_get_api_client(call_context, patched_api_client):
    result = await get_api_client(call_context)

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
        await get_api_client(call_context)

    _, error_details = str(error.value).split("\n", 1)
    assert json.loads(error_details) == {"hint": AUTH_HEADER_HINT}


async def test_get_marketplace_spec(api_client, registry_loader, spec_loader, endpoints_registry):
    registry_loader.return_value = endpoints_registry
    spec_loader.return_value = {"paths": {}}

    result = await get_marketplace_spec(api_client)

    assert result == MarketplaceSpec(
        api_base_url="https://api.test.com",
        audit_regex=FALLBACK_STATIC_REGEX,
        endpoints_registry=endpoints_registry,
        openapi=OpenAPISpec({"paths": {}}),
    )


async def test_get_marketplace_spec_load_fails(api_client, registry_loader):
    registry_loader.side_effect = OpenAPISpecFetchError("Connection refused")

    with pytest.raises(ToolError, match="Failed to load OpenAPI spec for your endpoint") as error:
        await get_marketplace_spec(api_client)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["api_endpoint"] == "https://api.test.com"
    assert details["details"] == "Connection refused"
