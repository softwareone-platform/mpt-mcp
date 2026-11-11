import asyncio
import datetime as dt
import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TokenValidationCache:
    """
    In-memory cache for token validations with TTL.

    Caches token validation results to avoid repeated API calls.
    Cache entries expire after a configurable TTL.
    """

    def __init__(self, ttl_minutes: int = 10):
        """
        Initialize token validation cache.

        Args:
            ttl_minutes: Time-to-live for cache entries in minutes (default: 10)
        """
        self.ttl = dt.timedelta(minutes=ttl_minutes)
        # Keyed by the SHA256 of token and endpoint, so raw tokens are not kept in memory
        self._cache: dict[str, tuple[bool, dt.datetime, dict[str, Any] | None]] = {}
        self._lock = asyncio.Lock()
        logger.info("Token validation cache initialized (TTL: %sm, secure hash keys)", ttl_minutes)

    async def clear(self) -> None:
        """Clear all cached validations."""
        async with self._lock:
            self._cache.clear()
            logger.info("Cleared all token validation cache")

    async def get(
        self,
        token: str,
        api_base_url: str,
    ) -> tuple[bool, dict[str, Any] | None] | None:
        """
        Get cached validation result for a token.

        Args:
            token: The API token to check
            api_base_url: The API endpoint

        Returns:
            Tuple of (is_valid, token_info) if cached and not expired, None otherwise
        """
        cache_key = self._cache_key(token, api_base_url)

        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                is_valid, expiry, token_info = cached

                if dt.datetime.now(dt.UTC) < expiry:
                    logger.debug(
                        "Token validation cache hit (expires in %ss)",
                        (expiry - dt.datetime.now(dt.UTC)).seconds,
                    )
                    return (is_valid, token_info)

                logger.debug("Token validation cache expired, removing")
                self._cache.pop(cache_key)

            return None

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        now = dt.datetime.now(dt.UTC)
        expiries = [expiry for _, expiry, _ in self._cache.values()]
        valid_count = sum(1 for expiry in expiries if expiry > now)
        expired_count = len(self._cache) - valid_count

        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "ttl_minutes": self.ttl.total_seconds() / 60,
        }

    async def invalidate(self, token: str, api_base_url: str) -> None:
        """
        Invalidate a specific token in the cache.

        Args:
            token: The API token to invalidate
            api_base_url: The API endpoint
        """
        cache_key = self._cache_key(token, api_base_url)

        async with self._lock:
            if self._cache.pop(cache_key, None) is not None:
                logger.debug("Invalidated token from cache")

    async def set(
        self,
        token: str,
        api_base_url: str,
        *,
        is_valid: bool,
        token_info: dict[str, Any] | None = None,
    ) -> None:
        """
        Cache validation result for a token.

        Args:
            token: The API token
            api_base_url: The API endpoint
            is_valid: Whether the token is valid
            token_info: Optional token metadata from API response
        """
        cache_key = self._cache_key(token, api_base_url)

        async with self._lock:
            expiry = dt.datetime.now(dt.UTC) + self.ttl
            self._cache[cache_key] = (is_valid, expiry, token_info)
            logger.debug(
                "Cached token validation (valid=%s, expires in %ss)", is_valid, self.ttl.seconds
            )

    def _cache_key(self, token: str, api_base_url: str) -> str:
        combined = f"{token}|{api_base_url}"
        return hashlib.sha256(combined.encode()).hexdigest()
