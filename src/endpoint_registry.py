import asyncio
import json
import sys
from typing import Any

import httpx

from .cache_manager import CacheManager, fetch_with_cache
from .openapi_parser import OpenAPIParser


class OpenAPISpecFetchError(Exception):
    """Raised when the OpenAPI spec cannot be fetched from primary or fallback URL."""

    pass


# Global registries per API base URL
# Format: {api_base_url: {resource_id: endpoint_info}}
_endpoint_registries: dict[str, dict[str, dict[str, Any]]] = {}

# Global OpenAPI specs per API base URL (for schema lookups)
_openapi_specs: dict[str, dict[str, Any]] = {}

# Per-key async locks to dedupe concurrent first-loads and prevent a failing
# request from clobbering a good registry. Guarded by _registry_locks_guard.
_registry_locks: dict[str, asyncio.Lock] = {}
_registry_locks_guard = asyncio.Lock()

# Global cache manager (shared across all endpoints)
_cache_manager: CacheManager | None = None


def _log(message: str):
    """Log to stderr"""
    print(message, file=sys.stderr, flush=True)


def get_cache_manager() -> CacheManager:
    """Get or create the global cache manager"""
    global _cache_manager

    if _cache_manager is None:
        _cache_manager = CacheManager(cache_dir=".cache", ttl_hours=24)
        _log("✓ Cache manager initialized")

    return _cache_manager


def get_openapi_spec_url(api_base_url: str) -> str:
    """
    Derive the OpenAPI spec URL from the API base URL

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
    # Ensure no trailing slash
    api_base_url = api_base_url.rstrip("/")

    # OpenAPI spec is always at /public/v1/openapi.json
    return f"{api_base_url}/public/v1/openapi.json"


async def fetch_openapi_spec(api_base_url: str, force_refresh: bool = False) -> dict[str, Any]:
    """
    Fetch OpenAPI spec for a given API base URL with fallback

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

    # Get the OpenAPI spec URL for this endpoint
    openapi_url = get_openapi_spec_url(api_base_url)

    _log(f"📡 Loading OpenAPI spec from: {openapi_url}")

    try:
        # Try to fetch from the endpoint-specific URL
        spec = await fetch_with_cache(url=openapi_url, cache_manager=cache_mgr, force_refresh=force_refresh)
        _log(f"✓ Loaded OpenAPI spec from {api_base_url}")
        return spec

    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log(f"⚠️  Failed to fetch from {openapi_url}: {e}")

        # If it's a 404, try the default fallback
        fallback_url = "https://api.platform.softwareone.com/public/v1/openapi.json"

        if openapi_url != fallback_url:
            _log(f"🔄 Trying fallback: {fallback_url}")

            try:
                spec = await fetch_with_cache(url=fallback_url, cache_manager=cache_mgr, force_refresh=force_refresh)
                _log("✓ Loaded OpenAPI spec from fallback")
                return spec

            except (httpx.HTTPError, httpx.TimeoutException, OSError, ValueError) as fallback_error:
                _log(f"❌ Fallback also failed: {fallback_error}")
                raise OpenAPISpecFetchError(f"Failed to fetch OpenAPI spec from both {openapi_url} and fallback {fallback_url}") from fallback_error

        # No fallback available, re-raise original error
        raise


async def _get_registry_lock(api_base_url: str) -> asyncio.Lock:
    """
    Get (creating if needed) the per-key async lock for an API base URL.

    Creation is serialized by _registry_locks_guard so concurrent callers share
    the same lock instance for a given key.
    """
    async with _registry_locks_guard:
        lock = _registry_locks.get(api_base_url)
        if lock is None:
            lock = asyncio.Lock()
            _registry_locks[api_base_url] = lock
        return lock


def _path_to_resource_id(path: str) -> str:
    """
    Convert an API path to a resource identifier

    Examples:
        /public/v1/catalog/products -> catalog.products
        /public/v1/catalog/items/{id} -> catalog.items.by_id
        /public/v1/commerce/orders -> commerce.orders
    """
    # Remove /public/v1/ prefix
    path = path.replace("/public/v1/", "")

    # Replace path parameters with descriptive names
    path = path.replace("/{id}", ".by_id")

    # Replace slashes with dots
    resource_id = path.replace("/", ".")

    return resource_id


async def get_endpoints_registry(api_base_url: str, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """
    Get or initialize the endpoints registry for a given API base URL

    Each API base URL has its own registry of endpoints parsed from its OpenAPI spec.
    Registries are cached in memory after first load.

    Args:
        api_base_url: The base URL of the API
        force_refresh: Force refresh the registry even if cached

    Returns:
        Dictionary mapping resource IDs to endpoint information
    """
    # Fast-path: return an already-cached registry without locking. A key is
    # only present after a successful load (failures never populate it), so
    # presence — not truthiness — is the correct cache-hit test.
    if not force_refresh and api_base_url in _endpoint_registries:
        _log(f"✓ Using cached endpoints registry for {api_base_url}")
        return _endpoint_registries[api_base_url]

    # Serialize concurrent first-loads for this key so a single fetch populates
    # the cache and a failing request cannot clobber a good registry.
    lock = await _get_registry_lock(api_base_url)
    async with lock:
        # Re-check inside the lock: another coroutine may have populated the
        # registry while we were waiting to acquire the lock.
        if not force_refresh and api_base_url in _endpoint_registries:
            _log(f"✓ Using cached endpoints registry for {api_base_url}")
            return _endpoint_registries[api_base_url]

        _log(f"🔄 Initializing endpoints registry for {api_base_url}")

        try:
            # Fetch the OpenAPI spec for this endpoint
            spec = await fetch_openapi_spec(api_base_url, force_refresh=force_refresh)

            # Store the full OpenAPI spec for schema lookups
            _openapi_specs[api_base_url] = spec

            # Parse the OpenAPI spec
            parser = OpenAPIParser()
            tools = parser.extract_get_endpoints(spec)

            # Build the registry with richer metadata
            registry: dict[str, dict[str, Any]] = {}

            for tool in tools:
                tool_info = json.loads(tool.description)
                path = tool_info.get("path", "")

                # Create a resource identifier from the path
                resource_id = _path_to_resource_id(path)

                registry[resource_id] = {
                    "path": path,
                    "summary": tool_info.get("summary", ""),
                    "description": tool_info.get("description", ""),
                    "parameters": tool_info.get("parameters", []),
                    "response": tool_info.get("response", {}),
                }

            # Cache the registry. Reached only on a successful fetch+parse, so
            # the key is set here and never on the failure path below.
            _endpoint_registries[api_base_url] = registry

            # Build audit fields cache from spec (for auto-add regex and marketplace_audit_fields tool)
            try:
                from . import audit_fields

                await asyncio.to_thread(audit_fields.update_cache, api_base_url, spec, _path_to_resource_id)
                _log(f"✓ Audit fields cache updated for {api_base_url}")
            except Exception as audit_err:
                _log(f"⚠ Audit fields cache skipped: {audit_err}")

            _log(f"✓ Discovered {len(registry)} GET endpoints for {api_base_url}")
            _log(f"✓ Stored in registry with {len(registry)} resource IDs")

            return registry

        except Exception as e:
            _log(f"❌ Failed to initialize endpoints registry for {api_base_url}: {e}")
            # Do NOT cache the failure: leaving the key unset lets the next
            # request retry instead of being bricked with {} until restart.
            return {}


def clear_registry(api_base_url: str | None = None):
    """
    Clear the endpoints registry cache

    Args:
        api_base_url: If provided, clear only this endpoint's registry.
                     If None, clear all registries.
    """
    global _endpoint_registries

    if api_base_url:
        if api_base_url in _endpoint_registries:
            del _endpoint_registries[api_base_url]
            _log(f"✓ Cleared registry for {api_base_url}")
    else:
        _endpoint_registries = {}
        _log("✓ Cleared all endpoint registries")


def get_all_registries() -> dict[str, dict[str, dict[str, Any]]]:
    """
    Get all cached endpoint registries

    Returns:
        Dictionary mapping API base URLs to their endpoint registries
    """
    return _endpoint_registries.copy()


async def get_openapi_spec(api_base_url: str, force_refresh: bool = False) -> dict[str, Any]:
    """
    Get the OpenAPI specification for a given API base URL

    Args:
        api_base_url: The base URL of the API
        force_refresh: Force refresh the spec even if cached

    Returns:
        OpenAPI specification dictionary
    """
    # Ensure the registry is initialized (which caches the spec)
    await get_endpoints_registry(api_base_url, force_refresh=force_refresh)

    # Return the cached spec
    return _openapi_specs.get(api_base_url, {})
