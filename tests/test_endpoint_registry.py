from unittest.mock import AsyncMock, patch

import pytest

from mpt_mcp.endpoint_registry import get_openapi_spec


@pytest.fixture
def unique_endpoint(request):
    # get_openapi_spec caches per endpoint for the whole process, so every test uses its own
    # endpoint
    slug = request.node.name.replace("_", "-").replace("[", "-").replace("]", "")
    return f"https://{slug}.test.com"


@pytest.fixture
def fetch_openapi_spec():
    with patch(
        "mpt_mcp.endpoint_registry.fetch_openapi_spec", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.side_effect = lambda endpoint, force_refresh=False: {
            "openapi": "3.0.0",
            "info": {"title": endpoint},
        }
        yield mock_fetch


async def test_get_openapi_spec_fetches_spec_for_endpoint(fetch_openapi_spec, unique_endpoint):
    result = await get_openapi_spec(unique_endpoint)

    assert result == {"openapi": "3.0.0", "info": {"title": unique_endpoint}}


async def test_get_openapi_spec_caches_spec_per_endpoint(fetch_openapi_spec, unique_endpoint):
    await get_openapi_spec(unique_endpoint)
    await get_openapi_spec(f"{unique_endpoint}.other")

    await get_openapi_spec(unique_endpoint)  # act

    assert fetch_openapi_spec.await_count == 2
