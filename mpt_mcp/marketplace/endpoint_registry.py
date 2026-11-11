import logging
from typing import Any

import httpx

from mpt_mcp.marketplace.cache_manager import CacheManager, fetch_with_cache
from mpt_mcp.marketplace.openapi_parser import OpenAPIParser

logger = logging.getLogger(__name__)

FALLBACK_OPENAPI_URL = "https://api.platform.softwareone.com/public/v1/openapi.json"


class OpenAPISpecFetchError(Exception):
    """Raised when the OpenAPI spec cannot be fetched or read, from the endpoint or the fallback."""


# Endpoint info by resource ID
type EndpointRegistry = dict[str, dict[str, Any]]


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


async def fetch_openapi_spec(
    api_base_url: str,
    cache_manager: CacheManager,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch OpenAPI spec for a given API base URL with fallback.

    First tries the endpoint-specific OpenAPI URL.
    If that fails (404), falls back to the default production endpoint.

    Args:
        api_base_url: The base URL of the API
        cache_manager: Disk cache of the fetched specs
        force_refresh: Force refresh cache even if valid cache exists

    Returns:
        OpenAPI specification dictionary

    Raises:
        OpenAPISpecFetchError: The spec request failed (also from the fallback URL), timed out,
            or its cache file or JSON could not be read
    """
    openapi_url = get_openapi_spec_url(api_base_url)

    logger.info("Loading OpenAPI spec from: %s", openapi_url)

    try:
        spec = await fetch_with_cache(
            url=openapi_url, cache_manager=cache_manager, force_refresh=force_refresh
        )
    except httpx.HTTPError as error:
        logger.warning("Failed to fetch from %s: %s", openapi_url, error)
        if openapi_url == FALLBACK_OPENAPI_URL:
            raise OpenAPISpecFetchError(
                f"Failed to fetch OpenAPI spec from {openapi_url}"
            ) from error

        return await fetch_fallback_openapi_spec(
            openapi_url, cache_manager, force_refresh=force_refresh
        )
    except (OSError, ValueError) as error:
        # Timeouts are OSError too; ValueError is a spec or cache file that is not valid JSON
        raise OpenAPISpecFetchError(f"Failed to read OpenAPI spec from {openapi_url}") from error

    logger.info("Loaded OpenAPI spec from %s", api_base_url)
    return spec


async def fetch_fallback_openapi_spec(
    openapi_url: str,
    cache_manager: CacheManager,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch the OpenAPI spec of the production endpoint, when the caller's endpoint has none.

    Args:
        openapi_url: OpenAPI spec URL of the caller's endpoint, which could not be fetched
        cache_manager: Disk cache of the fetched specs
        force_refresh: Force refresh cache even if valid cache exists

    Returns:
        OpenAPI specification dictionary of the production endpoint

    Raises:
        OpenAPISpecFetchError: The fallback spec could not be fetched or read either
    """
    logger.info("Trying fallback: %s", FALLBACK_OPENAPI_URL)
    try:
        spec = await fetch_with_cache(
            url=FALLBACK_OPENAPI_URL, cache_manager=cache_manager, force_refresh=force_refresh
        )
    except (httpx.HTTPError, OSError, ValueError) as fallback_error:
        logger.exception("Fallback also failed")
        raise OpenAPISpecFetchError(
            f"Failed to fetch OpenAPI spec from both {openapi_url} and fallback "
            f"{FALLBACK_OPENAPI_URL}"
        ) from fallback_error

    logger.info("Loaded OpenAPI spec from fallback")
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
