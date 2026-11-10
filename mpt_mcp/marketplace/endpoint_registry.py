import functools
import logging
from typing import Any

import httpx

from mpt_mcp.marketplace.cache_manager import CacheManager, fetch_with_cache
from mpt_mcp.marketplace.openapi_parser import OpenAPIParser

logger = logging.getLogger(__name__)


class OpenAPISpecFetchError(Exception):
    """Raised when the OpenAPI spec cannot be fetched or read, from the endpoint or the fallback."""


# Endpoint info by resource ID
type EndpointRegistry = dict[str, dict[str, Any]]


@functools.cache
def get_cache_manager() -> CacheManager:
    """Get the OpenAPI spec disk cache of the process, created on the first call."""
    logger.info("Cache manager initialized")
    return CacheManager(cache_dir=".cache", ttl_hours=24)


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
        OpenAPISpecFetchError: The spec request failed (also from the fallback URL), timed out,
            or its cache file or JSON could not be read
    """
    cache_mgr = get_cache_manager()

    openapi_url = get_openapi_spec_url(api_base_url)

    logger.info("Loading OpenAPI spec from: %s", openapi_url)

    try:
        spec = await fetch_with_cache(
            url=openapi_url, cache_manager=cache_mgr, force_refresh=force_refresh
        )
    except httpx.HTTPError as error:
        logger.warning("Failed to fetch from %s: %s", openapi_url, error)

        fallback_url = "https://api.platform.softwareone.com/public/v1/openapi.json"

        if openapi_url != fallback_url:
            logger.info("Trying fallback: %s", fallback_url)

            try:
                spec = await fetch_with_cache(
                    url=fallback_url, cache_manager=cache_mgr, force_refresh=force_refresh
                )
            except (httpx.HTTPError, OSError, ValueError) as fallback_error:
                logger.exception("Fallback also failed")
                raise OpenAPISpecFetchError(
                    f"Failed to fetch OpenAPI spec from both {openapi_url} and fallback "
                    f"{fallback_url}"
                ) from fallback_error

            logger.info("Loaded OpenAPI spec from fallback")
            return spec

        raise OpenAPISpecFetchError(f"Failed to fetch OpenAPI spec from {openapi_url}") from error
    except (OSError, ValueError) as error:
        # Timeouts are OSError too; ValueError is a spec or cache file that is not valid JSON
        raise OpenAPISpecFetchError(f"Failed to read OpenAPI spec from {openapi_url}") from error

    logger.info("Loaded OpenAPI spec from %s", api_base_url)
    return spec


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


def build_endpoints_registry(spec: dict[str, Any]) -> EndpointRegistry:
    """
    Build the registry of the GET endpoints of an OpenAPI spec.

    Args:
        spec: OpenAPI spec of a Marketplace endpoint

    Returns:
        Endpoint info by resource ID: its API path, summary, description and parameters
    """
    return {
        path_to_resource_id(endpoint["path"]): endpoint
        for endpoint in OpenAPIParser().extract_get_endpoints(spec)
    }
