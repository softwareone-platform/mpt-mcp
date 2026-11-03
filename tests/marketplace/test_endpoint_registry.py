from unittest.mock import AsyncMock, patch

import pytest

from mpt_mcp.marketplace.endpoint_registry import get_openapi_spec

SLUG_TRANSLATION = str.maketrans({"_": "-", "[": "-", "]": None})


@pytest.fixture
def unique_endpoint(request):
    slug = request.node.name.translate(SLUG_TRANSLATION)
    return f"https://{slug}.test.com"


@pytest.fixture
def fetch_openapi_spec():
    with patch(
        "mpt_mcp.marketplace.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.side_effect = lambda endpoint, force_refresh=False: {
            "openapi": "3.0.0",
            "info": {"title": endpoint},
        }
        yield mock_fetch


async def test_get_openapi_spec_fetches_spec(fetch_openapi_spec, unique_endpoint):
    result = await get_openapi_spec(unique_endpoint)

    assert result == {"openapi": "3.0.0", "info": {"title": unique_endpoint}}


async def test_get_openapi_spec_retries_after_failure(fetch_openapi_spec, unique_endpoint):
    fetch_openapi_spec.side_effect = [RuntimeError("Connection refused"), {"openapi": "3.0.0"}]

    with pytest.raises(RuntimeError):
        await get_openapi_spec(unique_endpoint)

    result = await get_openapi_spec(unique_endpoint)
    assert result == {"openapi": "3.0.0"}


async def test_get_openapi_spec_caches_per_endpoint(fetch_openapi_spec, unique_endpoint):
    await get_openapi_spec(unique_endpoint)
    await get_openapi_spec(f"{unique_endpoint}.other")

    await get_openapi_spec(unique_endpoint)  # act

    assert fetch_openapi_spec.await_count == 2
