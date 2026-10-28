import asyncio
import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_FETCH_TIMEOUT = 30.0


def _read_json_path(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file (sync; run via asyncio.to_thread from async code)."""
    with Path(path).open(encoding="utf-8") as json_file:
        return json.load(json_file)


class CacheManager:
    """Manages caching of OpenAPI specs and endpoint metadata."""

    def __init__(self, cache_dir: str = ".cache", ttl_hours: int = 24):
        """
        Initialize cache manager.

        Args:
            cache_dir: Directory to store cache files
            ttl_hours: Cache time-to-live in hours (default: 24)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.ttl = dt.timedelta(hours=ttl_hours)

    def get_cache_path(self, key: str) -> Path:
        """Get cache file path for a given key."""
        # Hash the key to create a safe filename
        key_hash = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

    def _get_metadata_path(self, key: str) -> Path:
        """Get metadata file path for a given key."""
        key_hash = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()
        return self.cache_dir / f"{key_hash}.meta.json"

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached data is still valid (not expired)."""
        meta_path = self._get_metadata_path(key)

        if not meta_path.exists():
            return False

        try:
            with Path(meta_path).open(encoding="utf-8") as meta_handle:
                metadata = json.load(meta_handle)

            cached_at = dt.datetime.fromisoformat(metadata.get("cached_at"))
            expires_at = cached_at + self.ttl

            return dt.datetime.now() < expires_at
        except KeyError, ValueError:
            return False

    def get(self, key: str) -> dict[str, Any] | None:
        """
        Get cached data if available and valid.

        Args:
            key: Cache key (usually the URL)

        Returns:
            Cached data or None if not available/expired
        """
        cache_path = self.get_cache_path(key)

        if not cache_path.exists():
            return None

        if not self._is_cache_valid(key):
            return None

        try:
            with Path(cache_path).open(encoding="utf-8") as cache_handle:
                return json.load(cache_handle)
        except OSError, json.JSONDecodeError:
            return None

    def set(self, key: str, data: dict[str, Any]) -> None:
        """
        Store data in cache.

        Args:
            key: Cache key (usually the URL)
            data: Data to cache
        """
        cache_path = self.get_cache_path(key)
        meta_path = self._get_metadata_path(key)

        # Write data
        with Path(cache_path).open("w", encoding="utf-8") as cache_handle:
            json.dump(data, cache_handle, indent=2)

        # Write metadata
        metadata = {
            "cached_at": dt.datetime.now().isoformat(),
            "key": key,
            "size": len(json.dumps(data)),
        }
        with Path(meta_path).open("w", encoding="utf-8") as meta_handle:
            json.dump(metadata, meta_handle, indent=2)

    def invalidate(self, key: str) -> None:
        """
        Invalidate (delete) cached data for a key.

        Args:
            key: Cache key to invalidate
        """
        cache_path = self.get_cache_path(key)
        meta_path = self._get_metadata_path(key)

        if cache_path.exists():
            cache_path.unlink()
        if meta_path.exists():
            meta_path.unlink()

    def get_cache_info(self) -> dict[str, Any]:
        """
        Get information about the cache.

        Returns:
            Dictionary with cache statistics
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        data_files = [
            meta_handle
            for meta_handle in cache_files
            if not meta_handle.name.endswith(".meta.json")
        ]

        total_size = sum(meta_handle.stat().st_size for meta_handle in cache_files)

        valid_count = 0
        expired_count = 0

        for data_file in data_files:
            key_hash = data_file.stem
            meta_file = self.cache_dir / f"{key_hash}.meta.json"

            if meta_file.exists():
                try:
                    with Path(meta_file).open(encoding="utf-8") as meta_handle:
                        metadata = json.load(meta_handle)

                    cached_at = dt.datetime.fromisoformat(metadata.get("cached_at"))
                    expires_at = cached_at + self.ttl

                    if dt.datetime.now() < expires_at:
                        valid_count += 1
                    else:
                        expired_count += 1
                except KeyError, ValueError:
                    expired_count += 1

        return {
            "cache_directory": str(self.cache_dir.absolute()),
            "total_entries": len(data_files),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "total_size_bytes": total_size,
            "ttl_hours": self.ttl.total_seconds() / 3600,
        }


async def fetch_with_cache(
    url: str,
    cache_manager: CacheManager,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch data from URL with caching.

    Args:
        url: URL to fetch
        cache_manager: Cache manager instance
        force_refresh: Force refresh even if cache is valid

    Returns:
        Fetched or cached data

    Raises:
        httpx.HTTPError: If fetch fails and no cache available
    """
    # Try cache first (unless force refresh)
    if not force_refresh:
        cached_data = cache_manager.get(url)
        if cached_data is not None:
            logger.info("✓ Using cached data from: %s", url)
            return cached_data

    # Fetch from network (connect and default DEFAULT_FETCH_TIMEOUT, connect at least 30s)
    logger.info("📡 Fetching from: %s", url)
    try:
        timeout_config = httpx.Timeout(DEFAULT_FETCH_TIMEOUT, connect=30.0)
        async with asyncio.timeout(DEFAULT_FETCH_TIMEOUT):
            async with httpx.AsyncClient(
                follow_redirects=True, http2=True, timeout=timeout_config
            ) as client:
                response = await client.get(url)

            # Log if redirects occurred
            if len(response.history) > 0:
                logger.info("🔄 Followed %s redirect(s)", len(response.history))
                for position, redirect in enumerate(response.history, 1):
                    logger.info(
                        "   %s. %s → %s",
                        position,
                        redirect.status_code,
                        redirect.headers.get("Location", "unknown"),
                    )
                logger.info("   Final: %s", response.url)

            response.raise_for_status()
            data = response.json()

        # Cache the result
        cache_manager.set(url, data)
        logger.info("✓ Cached data from: %s", url)

        return data

    except (TimeoutError, httpx.HTTPError, httpx.TimeoutException) as error:
        # If fetch fails (timeout or HTTP error), try to use expired cache as fallback
        logger.warning("⚠ Network fetch failed: %s", error)

        cache_path = cache_manager.get_cache_path(url)
        if cache_path.exists():
            logger.warning("⚠ Using expired cache as fallback")
            return await asyncio.to_thread(_read_json_path, cache_path)

        # No cache available, re-raise the error
        raise
