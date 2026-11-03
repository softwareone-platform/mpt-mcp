import asyncio
import logging
from typing import Any

import httpx

from mpt_mcp.marketplace import audit_fields
from mpt_mcp.marketplace.cache_manager import CacheManager, fetch_with_cache
from mpt_mcp.marketplace.openapi_parser import OpenAPIParser

logger = logging.getLogger(__name__)


class OpenAPISpecFetchError(Exception):
    """Raised when the OpenAPI spec cannot be fetched from primary or fallback URL."""


# Keyed by API base URL, then by resource ID, holding each endpoint's info
_endpoint_registries: dict[str, dict[str, dict[str, Any]]] = {}
_openapi_specs: dict[str, dict[str, Any]] = {}
_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    """Get or create the global cache manager."""
    global _cache_manager

    if _cache_manager is None:
        _cache_manager = CacheManager(cache_dir=".cache", ttl_hours=24)
        logger.info("Cache manager initialized")

    return _cache_manager


def get_openapi_spec_url(api_base_url: str) -> str:
    """
    Derive the OpenAPI spec URL from the API base URL.

    The OpenAPI spec is always at: {api_base_url}/public/v1/openapi.json

    Examples:
        https://api.s1.show -> https://api.s1.show/public/v1/openapi.json
        https://api.platform.softwareone.com -> https://api.platform.softwareone.com/public/v1/openapi.json
        https://custom-api.example.com -> https://custom-api.example.com/public/v1/openapi.json

    Args:
        api_base_url: The base URL of the API (scheme://hostname[:port])

    Returns:
        Full URL to the OpenAPI specification
    """
    api_base_url = api_base_url.rstrip("/")

    return f"{api_base_url}/public/v1/openapi.json"


async def fetch_openapi_spec(api_base_url: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """
    Fetch OpenAPI spec for a given API base URL with fallback.

    First tries the endpoint-specific OpenAPI URL.
    If that fails (404), falls back to the default production endpoint.

    Args:
        api_base_url: The base URL of the API
        force_refresh: Force refresh cache even if valid cache exists

    Returns:
        OpenAPI specification dictionary

    Raises:
        Exception: If both primary and fallback fetches fail
    """
    cache_mgr = get_cache_manager()

    openapi_url = get_openapi_spec_url(api_base_url)

    logger.info("Loading OpenAPI spec from: %s", openapi_url)

    try:
        spec = await fetch_with_cache(
            url=openapi_url, cache_manager=cache_mgr, force_refresh=force_refresh
        )
        logger.info("Loaded OpenAPI spec from %s", api_base_url)
        return spec

    except (httpx.HTTPError, httpx.TimeoutException) as error:
        logger.warning("Failed to fetch from %s: %s", openapi_url, error)

        fallback_url = "https://api.platform.softwareone.com/public/v1/openapi.json"

        if openapi_url != fallback_url:
            logger.info("Trying fallback: %s", fallback_url)

            try:
                spec = await fetch_with_cache(
                    url=fallback_url, cache_manager=cache_mgr, force_refresh=force_refresh
                )
                logger.info("Loaded OpenAPI spec from fallback")
                return spec

            except (httpx.HTTPError, httpx.TimeoutException, OSError, ValueError) as fallback_error:
                logger.exception("Fallback also failed")
                raise OpenAPISpecFetchError(
                    f"Failed to fetch OpenAPI spec from both {openapi_url} and fallback "
                    f"{fallback_url}"
                ) from fallback_error

        raise


def path_to_resource_id(path: str) -> str:
    """
    Convert an API path to a resource identifier.

    Examples:
        /public/v1/catalog/products -> catalog.products
        /public/v1/catalog/items/{id} -> catalog.items.by_id
        /public/v1/commerce/orders -> commerce.orders
    """
    path = path.replace("/public/v1/", "")

    path = path.replace("/{id}", ".by_id")

    return path.replace("/", ".")


async def get_endpoints_registry(
    api_base_url: str, *, force_refresh: bool = False
) -> dict[str, dict[str, Any]]:
    """
    Get or initialize the endpoints registry for a given API base URL.

    Each API base URL has its own registry of endpoints parsed from its OpenAPI spec.
    Registries are cached in memory after first load.

    Args:
        api_base_url: The base URL of the API
        force_refresh: Force refresh the registry even if cached

    Returns:
        Dictionary mapping resource IDs to endpoint information

    Raises:
        Exception: The OpenAPI spec could not be fetched or parsed
    """
    if api_base_url in _endpoint_registries and not force_refresh:
        logger.info("Using cached endpoints registry for %s", api_base_url)
        return _endpoint_registries[api_base_url]

    logger.info("Initializing endpoints registry for %s", api_base_url)

    try:
        spec = await fetch_openapi_spec(api_base_url, force_refresh=force_refresh)

        _openapi_specs[api_base_url] = spec

        parser = OpenAPIParser()
        registry: dict[str, dict[str, Any]] = {
            path_to_resource_id(endpoint["path"]): endpoint
            for endpoint in parser.extract_get_endpoints(spec)
        }

        _endpoint_registries[api_base_url] = registry

        try:
            await asyncio.to_thread(
                audit_fields.update_cache, api_base_url, spec, path_to_resource_id
            )
            logger.info("Audit fields cache updated for %s", api_base_url)
        except Exception as audit_err:
            logger.warning("Audit fields cache skipped: %s", audit_err)

        logger.info("Discovered %s GET endpoints for %s", len(registry), api_base_url)
        logger.info("Stored in registry with %s resource IDs", len(registry))

        return registry

    except Exception:
        # Nothing is cached, so the next call retries the spec instead of serving no resources
        logger.exception("Failed to initialize endpoints registry for %s", api_base_url)
        raise


async def get_openapi_spec(api_base_url: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """
    Get the OpenAPI specification for a given API base URL.

    Args:
        api_base_url: The base URL of the API
        force_refresh: Force refresh the spec even if cached

    Returns:
        OpenAPI specification dictionary
    """
    await get_endpoints_registry(api_base_url, force_refresh=force_refresh)

    return _openapi_specs.get(api_base_url, {})
