import asyncio
import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_FETCH_TIMEOUT = 30.0


def read_json_path(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file (sync; run via asyncio.to_thread from async code)."""
    with Path(path).open(encoding="utf-8") as json_file:
        document: dict[str, Any] = json.load(json_file)
        return document


def read_cached_at(cached_at: str) -> dt.datetime:
    """
    Read the time a cache entry was written.

    Entries written before times were stored in UTC have no time zone; they are read as UTC.

    Args:
        cached_at: ISO 8601 time from the entry's metadata

    Returns:
        Time in UTC

    Raises:
        ValueError: The time is not in ISO 8601 format
    """
    written_at = dt.datetime.fromisoformat(cached_at)
    if written_at.tzinfo is None:
        return written_at.replace(tzinfo=dt.UTC)
    return written_at


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
                cached: dict[str, Any] = json.load(cache_handle)
                return cached
        except OSError, json.JSONDecodeError:
            return None

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
            meta_file = self.cache_dir / f"{data_file.stem}.meta.json"
            if not meta_file.exists():
                continue
            if self._is_metadata_valid(meta_file):
                valid_count += 1
            else:
                expired_count += 1

        return {
            "cache_directory": str(self.cache_dir.absolute()),
            "total_entries": len(data_files),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "total_size_bytes": total_size,
            "ttl_hours": self.ttl / dt.timedelta(hours=1),
        }

    def get_cache_path(self, key: str) -> Path:
        """Get cache file path for a given key."""
        key_hash = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

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

    def set(self, key: str, data: dict[str, Any]) -> None:
        """
        Store data in cache.

        Args:
            key: Cache key (usually the URL)
            data: Data to cache
        """
        cache_path = self.get_cache_path(key)
        meta_path = self._get_metadata_path(key)

        with Path(cache_path).open("w", encoding="utf-8") as cache_handle:
            json.dump(data, cache_handle, indent=2)

        metadata = {
            "cached_at": dt.datetime.now(dt.UTC).isoformat(),
            "key": key,
            "size": len(json.dumps(data)),
        }
        with Path(meta_path).open("w", encoding="utf-8") as meta_handle:
            json.dump(metadata, meta_handle, indent=2)

    def _get_metadata_path(self, key: str) -> Path:
        key_hash = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()
        return self.cache_dir / f"{key_hash}.meta.json"

    def _is_cache_valid(self, key: str) -> bool:
        meta_path = self._get_metadata_path(key)

        if not meta_path.exists():
            return False

        return self._is_metadata_valid(meta_path)

    def _is_metadata_valid(self, meta_path: Path) -> bool:
        try:
            cached_at = read_cached_at(read_json_path(meta_path)["cached_at"])
        except KeyError, ValueError:
            return False
        return dt.datetime.now(dt.UTC) < cached_at + self.ttl


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
    if not force_refresh:
        cached_data = cache_manager.get(url)
        if cached_data is not None:
            logger.info("Using cached data from: %s", url)
            return cached_data

    logger.info("Fetching from: %s", url)
    try:
        data = await fetch_json(url)
    except (TimeoutError, httpx.HTTPError) as error:
        # If fetch fails (timeout or HTTP error), try to use expired cache as fallback
        logger.warning("Network fetch failed: %s", error)

        cache_path = cache_manager.get_cache_path(url)
        if cache_path.exists():
            logger.warning("Using expired cache as fallback")
            return await asyncio.to_thread(read_json_path, cache_path)

        raise

    cache_manager.set(url, data)
    logger.info("Cached data from: %s", url)

    return data


async def fetch_json(url: str) -> dict[str, Any]:
    """
    Fetch a JSON document, logging the redirects followed to reach it.

    Args:
        url: URL to fetch

    Returns:
        Parsed JSON document

    Raises:
        TimeoutError: If the whole fetch takes longer than DEFAULT_FETCH_TIMEOUT
        httpx.HTTPError: If the request fails or the response status is an error
    """
    timeout_config = httpx.Timeout(DEFAULT_FETCH_TIMEOUT, connect=DEFAULT_CONNECT_TIMEOUT)
    async with asyncio.timeout(DEFAULT_FETCH_TIMEOUT):
        async with httpx.AsyncClient(
            follow_redirects=True, http2=True, timeout=timeout_config
        ) as client:
            response = await client.get(url)
        log_redirects(response)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def log_redirects(response: httpx.Response) -> None:
    """
    Log the redirects followed to reach a response.

    Args:
        response: Response at the end of the redirects
    """
    if not response.history:
        return

    logger.info("Followed %s redirect(s)", len(response.history))
    for position, redirect in enumerate(response.history, 1):
        logger.info(
            "%s. %s → %s",
            position,
            redirect.status_code,
            redirect.headers.get("Location", "unknown"),
        )
    logger.info("Final: %s", response.url)
