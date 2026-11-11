import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from fastmcp.server.lifespan import lifespan

from mpt_mcp.marketplace.cache_manager import CacheManager
from mpt_mcp.marketplace.endpoint_registry import fetch_openapi_spec
from mpt_mcp.tools.spec import MarketplaceSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

SPEC_STORE_KEY = "marketplace_specs"


class MarketplaceSpecStore:
    """Specs of the Marketplace endpoints of the callers, loaded on each endpoint's first call."""

    def __init__(self, cache_manager: CacheManager | None = None) -> None:
        # Fetched specs are also kept on disk, so a restart or another process reuses them
        self.cache_manager = cache_manager or CacheManager(cache_dir=".cache", ttl_hours=24)
        self._specs: dict[str, MarketplaceSpec] = {}
        # One load per endpoint at a time, so concurrent first calls fetch the spec once
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def get(self, api_base_url: str, *, force_refresh: bool = False) -> MarketplaceSpec:
        """
        Return the spec of an endpoint, loading it on its first call.

        A failed load is not kept, so the next call retries it.

        Args:
            api_base_url: Base URL of the endpoint
            force_refresh: Fetch the spec again, even when it is loaded or in the disk cache

        Returns:
            Spec, endpoints registry and audit events of the endpoint

        Raises:
            OpenAPISpecFetchError: The OpenAPI spec could not be fetched or read
        """
        async with self._locks[api_base_url]:
            spec = self._specs.get(api_base_url)
            if spec is not None and not force_refresh:
                return spec

            document = await fetch_openapi_spec(
                api_base_url, self.cache_manager, force_refresh=force_refresh
            )
            spec = await asyncio.to_thread(MarketplaceSpec.from_document, api_base_url, document)
            self._specs[api_base_url] = spec
            return spec


@lifespan
async def spec_lifespan(server: Any) -> AsyncIterator[dict[str, Any]]:  # ruff: ignore[unused-async]
    """Give the server an empty spec store: each endpoint's spec loads on its first call."""
    yield {SPEC_STORE_KEY: MarketplaceSpecStore()}
