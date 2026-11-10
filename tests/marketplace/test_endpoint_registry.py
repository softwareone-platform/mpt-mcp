from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mpt_mcp.marketplace.endpoint_registry import (
    OpenAPISpecFetchError,
    build_endpoints_registry,
    fetch_openapi_spec,
)

FALLBACK_SPEC_URL = "https://api.platform.softwareone.com/public/v1/openapi.json"


@pytest.fixture
def cached_fetch():
    with patch(
        "mpt_mcp.marketplace.endpoint_registry.fetch_with_cache", new_callable=AsyncMock
    ) as mock_fetch:
        yield mock_fetch


def test_build_endpoints_registry():
    spec = {
        "paths": {
            "/public/v1/commerce/orders": {"get": {"summary": "List orders"}},
            "/public/v1/commerce/orders/{id}": {"get": {"summary": "Get an order"}},
        }
    }

    result = build_endpoints_registry(spec)

    assert list(result) == ["commerce.orders", "commerce.orders.by_id"]
    assert result["commerce.orders"]["path"] == "/public/v1/commerce/orders"


async def test_fetch_openapi_spec_uses_fallback(cached_fetch):
    cached_fetch.side_effect = [httpx.ConnectError("Connection refused"), {"openapi": "3.0.0"}]

    result = await fetch_openapi_spec("https://api.test.com")

    assert result == {"openapi": "3.0.0"}
    assert cached_fetch.call_args.kwargs["url"] == FALLBACK_SPEC_URL


@pytest.mark.parametrize(
    ("api_base_url", "fetch_errors"),
    [
        (
            "https://api.test.com",
            [httpx.ConnectError("Connection refused"), ValueError("Not JSON")],
        ),
        ("https://api.platform.softwareone.com", [httpx.ConnectError("Connection refused")]),
        ("https://api.test.com", [TimeoutError("Timed out")]),
        ("https://api.test.com", [ValueError("Not JSON")]),
    ],
)
async def test_fetch_openapi_spec_wraps_errors(cached_fetch, api_base_url, fetch_errors):
    cached_fetch.side_effect = fetch_errors

    with pytest.raises(OpenAPISpecFetchError) as error:
        await fetch_openapi_spec(api_base_url)

    assert error.value.__cause__ is fetch_errors[-1]
