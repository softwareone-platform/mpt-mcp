"""
Cache manager for OpenAPI spec and endpoint metadata
Reduces startup time and allows offline operation
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


class CacheManager:
    """Manages caching of OpenAPI specs and endpoint metadata"""

    def __init__(self, cache_dir: str = ".cache", ttl_hours: int = 24):
        """
        Initialize cache manager

        Args:
            cache_dir: Directory to store cache files
            ttl_hours: Cache time-to-live in hours (default: 24)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)

    def _get_cache_path(self, key: str) -> Path:
        """Get cache file path for a given key"""
        # Hash the key to create a safe filename
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

    def _get_metadata_path(self, key: str) -> Path:
        """Get metadata file path for a given key"""
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.meta.json"

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached data is still valid (not expired)"""
        meta_path = self._get_metadata_path(key)

        if not meta_path.exists():
            return False

        try:
            with open(meta_path) as f:
                metadata = json.load(f)

            cached_at = datetime.fromisoformat(metadata.get("cached_at"))
            expires_at = cached_at + self.ttl

            return datetime.now() < expires_at
        except (json.JSONDecodeError, KeyError, ValueError):
            return False

    def get(self, key: str) -> dict[str, Any] | None:
        """
        Get cached data if available and valid

        Args:
            key: Cache key (usually the URL)

        Returns:
            Cached data or None if not available/expired
        """
        cache_path = self._get_cache_path(key)

        if not cache_path.exists():
            return None

        if not self._is_cache_valid(key):
            return None

        try:
            with open(cache_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, key: str, data: dict[str, Any]) -> None:
        """
        Store data in cache

        Args:
            key: Cache key (usually the URL)
            data: Data to cache
        """
        cache_path = self._get_cache_path(key)
        meta_path = self._get_metadata_path(key)

        # Write data
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)

        # Write metadata
        metadata = {"cached_at": datetime.now().isoformat(), "key": key, "size": len(json.dumps(data))}
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

    def invalidate(self, key: str) -> None:
        """
        Invalidate (delete) cached data for a key

        Args:
            key: Cache key to invalidate
        """
        cache_path = self._get_cache_path(key)
        meta_path = self._get_metadata_path(key)

        if cache_path.exists():
            cache_path.unlink()
        if meta_path.exists():
            meta_path.unlink()

    def clear_all(self) -> int:
        """
        Clear all cached data

        Returns:
            Number of cache entries cleared
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1
        return count // 2  # Each entry has 2 files (data + metadata)

    def get_cache_info(self) -> dict[str, Any]:
        """
        Get information about the cache

        Returns:
            Dictionary with cache statistics
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        data_files = [f for f in cache_files if not f.name.endswith(".meta.json")]

        total_size = sum(f.stat().st_size for f in cache_files)

        valid_count = 0
        expired_count = 0

        for data_file in data_files:
            key_hash = data_file.stem
            meta_file = self.cache_dir / f"{key_hash}.meta.json"

            if meta_file.exists():
                try:
                    with open(meta_file) as f:
                        metadata = json.load(f)

                    cached_at = datetime.fromisoformat(metadata.get("cached_at"))
                    expires_at = cached_at + self.ttl

                    if datetime.now() < expires_at:
                        valid_count += 1
                    else:
                        expired_count += 1
                except (json.JSONDecodeError, KeyError, ValueError):
                    expired_count += 1

        return {
            "cache_directory": str(self.cache_dir.absolute()),
            "total_entries": len(data_files),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "total_size_bytes": total_size,
            "ttl_hours": self.ttl.total_seconds() / 3600,
        }


async def fetch_with_cache(url: str, cache_manager: CacheManager, force_refresh: bool = False, timeout: float = 30.0) -> dict[str, Any]:
    """
    Fetch data from URL with caching

    Args:
        url: URL to fetch
        cache_manager: Cache manager instance
        force_refresh: Force refresh even if cache is valid
        timeout: Request timeout in seconds

    Returns:
        Fetched or cached data

    Raises:
        httpx.HTTPError: If fetch fails and no cache available
    """
    import sys

    def log(message):
        print(message, file=sys.stderr, flush=True)

    # Try cache first (unless force refresh)
    if not force_refresh:
        cached_data = cache_manager.get(url)
        if cached_data is not None:
            log(f"✓ Using cached data from: {url}")
            return cached_data

    # Fetch from network
    log(f"📡 Fetching from: {url}")
    try:
        async with httpx.AsyncClient(follow_redirects=True, http2=True) as client:
            response = await client.get(url, timeout=timeout)

            # Log if redirects occurred
            if len(response.history) > 0:
                log(f"🔄 Followed {len(response.history)} redirect(s)")
                for i, redirect in enumerate(response.history, 1):
                    log(f"   {i}. {redirect.status_code} → {redirect.headers.get('Location', 'unknown')}")
                log(f"   Final: {response.url}")

            response.raise_for_status()
            data = response.json()

        # Cache the result
        cache_manager.set(url, data)
        log(f"✓ Cached data from: {url}")

        return data

    except (httpx.HTTPError, httpx.TimeoutException) as e:
        # If fetch fails, try to use expired cache as fallback
        log(f"⚠ Network fetch failed: {e}")

        cache_path = cache_manager._get_cache_path(url)
        if cache_path.exists():
            log("⚠ Using expired cache as fallback")
            with open(cache_path) as f:
                return json.load(f)

        # No cache available, re-raise the error
        raise
