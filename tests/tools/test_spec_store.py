import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from mpt_mcp.marketplace.endpoint_registry import OpenAPISpecFetchError
from mpt_mcp.tools.spec_store import SPEC_STORE_KEY, MarketplaceSpecStore, spec_lifespan


@pytest.fixture
def orders_spec():
    return {"paths": {"/public/v1/commerce/orders": {"get": {"summary": "List orders"}}}}


@pytest.fixture
def spec_fetcher(orders_spec):
    with patch(
        "mpt_mcp.tools.spec_store.fetch_openapi_spec", new_callable=AsyncMock
    ) as fetch_openapi_spec:
        fetch_openapi_spec.return_value = orders_spec
        yield fetch_openapi_spec


async def test_get_loads_spec(spec_fetcher, orders_spec):
    result = await MarketplaceSpecStore().get("https://api.test.com")

    assert result.api_base_url == "https://api.test.com"
    assert list(result.endpoints_registry) == ["commerce.orders"]
    assert result.openapi.document == orders_spec


async def test_get_keeps_spec_per_endpoint(spec_fetcher):
    spec_store = MarketplaceSpecStore()
    first_spec = await spec_store.get("https://api.test.com")
    await spec_store.get("https://api.other.com")

    result = await spec_store.get("https://api.test.com")

    assert result is first_spec
    assert spec_fetcher.await_count == 2


async def test_get_loads_once_for_concurrent_calls(spec_fetcher):
    spec_store = MarketplaceSpecStore()

    result = await asyncio.gather(
        spec_store.get("https://api.test.com"), spec_store.get("https://api.test.com")
    )

    assert result[0] is result[1]
    spec_fetcher.assert_awaited_once()


async def test_get_retries_after_failure(spec_fetcher, orders_spec):
    spec_store = MarketplaceSpecStore()
    spec_fetcher.side_effect = [OpenAPISpecFetchError("Connection refused"), orders_spec]
    with pytest.raises(OpenAPISpecFetchError):
        await spec_store.get("https://api.test.com")

    result = await spec_store.get("https://api.test.com")

    assert result.openapi.document == orders_spec


async def test_get_force_refresh_reloads(spec_fetcher):
    spec_store = MarketplaceSpecStore()
    first_spec = await spec_store.get("https://api.test.com")

    result = await spec_store.get("https://api.test.com", force_refresh=True)

    assert result is not first_spec
    spec_fetcher.assert_awaited_with(
        "https://api.test.com", spec_store.cache_manager, force_refresh=True
    )


async def test_spec_lifespan_gives_empty_store():
    async with spec_lifespan(FastMCP("test")) as lifespan_context:
        result = lifespan_context[SPEC_STORE_KEY]

    assert isinstance(result, MarketplaceSpecStore)
