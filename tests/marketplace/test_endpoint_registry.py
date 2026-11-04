from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mpt_mcp.marketplace.endpoint_registry import (
    OpenAPISpecFetchError,
    fetch_openapi_spec,
    get_openapi_spec,
)

FALLBACK_SPEC_URL = "https://api.platform.softwareone.com/public/v1/openapi.json"

SLUG_TRANSLATION = str.maketrans({"_": "-", "[": "-", "]": None})


@pytest.fixture
def unique_endpoint(request):
    slug = request.node.name.translate(SLUG_TRANSLATION)
    return f"https://{slug}.test.com"


@pytest.fixture
def spec_fetcher():
    with patch(
        "mpt_mcp.marketplace.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.side_effect = lambda endpoint, force_refresh=False: {
            "openapi": "3.0.0",
            "info": {"title": endpoint},
        }
        yield mock_fetch


@pytest.fixture
def cached_fetch():
    with patch(
        "mpt_mcp.marketplace.endpoint_registry.fetch_with_cache", new_callable=AsyncMock
    ) as mock_fetch:
        yield mock_fetch


async def test_get_openapi_spec_fetches_spec(spec_fetcher, unique_endpoint):
    result = await get_openapi_spec(unique_endpoint)

    assert result == {"openapi": "3.0.0", "info": {"title": unique_endpoint}}


async def test_get_openapi_spec_retries_after_failure(spec_fetcher, unique_endpoint):
    spec_fetcher.side_effect = [OpenAPISpecFetchError("Connection refused"), {"openapi": "3.0.0"}]

    with pytest.raises(OpenAPISpecFetchError):
        await get_openapi_spec(unique_endpoint)

    result = await get_openapi_spec(unique_endpoint)
    assert result == {"openapi": "3.0.0"}


async def test_get_openapi_spec_caches_per_endpoint(spec_fetcher, unique_endpoint):
    await get_openapi_spec(unique_endpoint)
    await get_openapi_spec(f"{unique_endpoint}.other")

    await get_openapi_spec(unique_endpoint)  # act

    assert spec_fetcher.await_count == 2


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
