#!/usr/bin/env python3
"""
Tests for the endpoints registry cache behavior (issue #8).

A transient failure on the first request for an endpoint must NOT poison the
in-process cache with an empty registry, which previously bricked all later
marketplace_query/resources/schema calls until process restart.
"""

import pytest

import src.endpoint_registry as endpoint_registry
from src.endpoint_registry import get_endpoints_registry


def _minimal_spec() -> dict:
    """A minimal but valid OpenAPI spec with one GET path.

    The parser yields at least one resource from this, so the resulting
    registry is non-empty.
    """
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/public/v1/catalog/products": {
                "get": {
                    "operationId": "listProducts",
                    "summary": "List products",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


@pytest.fixture(autouse=True)
def clear_registry_state():
    """Clear module-level registry/spec/lock state between tests."""
    endpoint_registry._endpoint_registries.clear()
    endpoint_registry._openapi_specs.clear()
    endpoint_registry._registry_locks.clear()
    yield
    endpoint_registry._endpoint_registries.clear()
    endpoint_registry._openapi_specs.clear()
    endpoint_registry._registry_locks.clear()


class TestRegistryNoPoison:
    """Transient failures must not poison the cache."""

    @pytest.mark.asyncio
    async def test_transient_failure_does_not_poison_cache(self, monkeypatch):
        url = "https://x.test"

        async def failing_fetch(api_base_url, force_refresh=False):
            raise RuntimeError("transient network error")

        monkeypatch.setattr("src.endpoint_registry.fetch_openapi_spec", failing_fetch)

        # First call fails transiently: returns {} but does NOT cache the failure.
        result = await get_endpoints_registry(url)
        assert result == {}
        assert url not in endpoint_registry._endpoint_registries

        # The transient condition clears; a later request must retry and succeed.
        async def good_fetch(api_base_url, force_refresh=False):
            return _minimal_spec()

        monkeypatch.setattr("src.endpoint_registry.fetch_openapi_spec", good_fetch)

        result = await get_endpoints_registry(url)
        assert result  # non-empty registry
        assert url in endpoint_registry._endpoint_registries
        assert endpoint_registry._endpoint_registries[url]

    @pytest.mark.asyncio
    async def test_successful_load_is_cached_and_served_from_cache(self, monkeypatch):
        url = "https://cached.test"
        call_count = 0

        async def counting_fetch(api_base_url, force_refresh=False):
            nonlocal call_count
            call_count += 1
            return _minimal_spec()

        monkeypatch.setattr("src.endpoint_registry.fetch_openapi_spec", counting_fetch)

        first = await get_endpoints_registry(url)
        assert first
        assert call_count == 1

        # Second call must be served from cache without re-fetching.
        second = await get_endpoints_registry(url)
        assert second == first
        assert call_count == 1
