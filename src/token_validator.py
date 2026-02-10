"""
Token Validator with In-Memory Cache

Validates API tokens against the Marketplace Platform API and caches results
to avoid repeated validation calls.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta

import httpx
from jose import jwt as jose_jwt

logger = logging.getLogger(__name__)


def _hash_token(token: str, api_base_url: str) -> str:
    """
    Create a secure hash of token + endpoint for cache key.

    This prevents storing full tokens in memory, reducing risk if memory is dumped.

    Args:
        token: The API token
        api_base_url: The API endpoint

    Returns:
        SHA256 hash as hex string
    """
    # Combine token and endpoint to ensure uniqueness per endpoint
    combined = f"{token}|{api_base_url}"
    return hashlib.sha256(combined.encode()).hexdigest()


class TokenValidationCache:
    """
    In-memory cache for token validations with TTL

    Caches token validation results to avoid repeated API calls.
    Cache entries expire after a configurable TTL.

    SECURITY: Uses SHA256 hash of token+endpoint as cache key instead of
    storing full tokens in memory. This prevents token exposure if memory is dumped.
    """

    def __init__(self, ttl_minutes: int = 60):
        """
        Initialize token validation cache

        Args:
            ttl_minutes: Time-to-live for cache entries in minutes (default: 60)
        """
        self.ttl = timedelta(minutes=ttl_minutes)
        # Cache format: {hash(token+endpoint): (is_valid, expiry_time, token_info)}
        # SECURITY: Keys are SHA256 hashes, not raw tokens
        self._cache: dict[str, tuple[bool, datetime, dict | None]] = {}
        self._lock = asyncio.Lock()
        logger.info(f"🔐 Token validation cache initialized (TTL: {ttl_minutes}m, secure hash keys)")

    async def get(self, token: str, api_base_url: str) -> tuple[bool, dict | None] | None:
        """
        Get cached validation result for a token

        Args:
            token: The API token to check
            api_base_url: The API endpoint

        Returns:
            Tuple of (is_valid, token_info) if cached and not expired, None otherwise
        """
        cache_key = _hash_token(token, api_base_url)

        async with self._lock:
            if cache_key in self._cache:
                is_valid, expiry, token_info = self._cache[cache_key]

                # Check if cache entry is still valid
                if datetime.now() < expiry:
                    logger.debug(f"✅ Token validation cache hit (expires in {(expiry - datetime.now()).seconds}s)")
                    return (is_valid, token_info)
                else:
                    # Cache expired, remove it
                    logger.debug("⏰ Token validation cache expired, removing")
                    del self._cache[cache_key]

            return None

    async def set(self, token: str, api_base_url: str, is_valid: bool, token_info: dict | None = None):
        """
        Cache validation result for a token

        Args:
            token: The API token
            api_base_url: The API endpoint
            is_valid: Whether the token is valid
            token_info: Optional token metadata from API response
        """
        cache_key = _hash_token(token, api_base_url)

        async with self._lock:
            expiry = datetime.now() + self.ttl
            self._cache[cache_key] = (is_valid, expiry, token_info)
            logger.debug(f"💾 Cached token validation (valid={is_valid}, expires in {self.ttl.seconds}s)")

    async def invalidate(self, token: str, api_base_url: str):
        """
        Invalidate a specific token in the cache

        Args:
            token: The API token to invalidate
            api_base_url: The API endpoint
        """
        cache_key = _hash_token(token, api_base_url)

        async with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.debug("🗑️  Invalidated token from cache")

    async def clear(self):
        """Clear all cached validations"""
        async with self._lock:
            self._cache.clear()
            logger.info("🗑️  Cleared all token validation cache")

    def get_stats(self) -> dict:
        """Get cache statistics"""
        now = datetime.now()
        valid_count = sum(1 for _, expiry, _ in self._cache.values() if expiry > now)
        expired_count = len(self._cache) - valid_count

        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "ttl_minutes": self.ttl.total_seconds() / 60,
        }


# Global token validation cache
_token_cache: TokenValidationCache | None = None


def get_token_cache(ttl_minutes: int = 60) -> TokenValidationCache:
    """Get or create the global token validation cache"""
    global _token_cache

    if _token_cache is None:
        _token_cache = TokenValidationCache(ttl_minutes=ttl_minutes)

    return _token_cache


def is_jwt_token(token: str) -> bool:
    """
    Check if a token is a JWT (JSON Web Token)

    JWT format: header.payload.signature (3 parts separated by dots)

    Args:
        token: The token string to check

    Returns:
        True if token appears to be a JWT, False otherwise
    """
    if not token or not isinstance(token, str):
        return False

    # JWT has exactly 3 parts separated by dots
    parts = token.split(".")
    return len(parts) == 3


def parse_jwt_claims(token: str) -> tuple[str | None, str | None]:
    """
    Parse user ID and account ID from a JWT token

    Extracts:
    - userId from claim: https://claims.softwareone.com/userId (format: USR-XXXX-XXXX)
    - accountId from claim: https://claims.softwareone.com/accountId (format: ACC-XXXX-XXXX)

    Args:
        token: The JWT token string

    Returns:
        Tuple of (user_id, account_id) or (None, None) if not found/invalid
    """
    try:
        # Decode JWT without verification (we'll validate via API call)
        # This is safe because we're only extracting claims, not trusting the token
        payload = jose_jwt.get_unverified_claims(token)

        # Extract userId from SoftwareOne custom claim
        user_id = payload.get("https://claims.softwareone.com/userId")
        if user_id and isinstance(user_id, str) and user_id.startswith("USR-"):
            user_id = user_id
        else:
            user_id = None

        # Extract accountId from SoftwareOne custom claim
        account_id = payload.get("https://claims.softwareone.com/accountId")
        if account_id and isinstance(account_id, str) and account_id.startswith("ACC-"):
            account_id = account_id
        else:
            account_id = None

        return (user_id, account_id)
    except Exception as e:
        logger.warning(f"Failed to parse JWT claims: {e}")
        return (None, None)


def parse_token_id(token: str) -> str | None:
    """
    Parse token ID from a token string

    Supports two formats:
    1. API Token: idt:TKN-XXXX-XXXX:secret_part
    2. JWT Token: header.payload.signature (extracts userId from claims)

    Args:
        token: The full token string

    Returns:
        Token ID (e.g., "TKN-1234-5678") or User ID (e.g., "USR-1234-5678") or None if invalid format
    """
    # First check if it's a JWT
    if is_jwt_token(token):
        user_id, _ = parse_jwt_claims(token)
        if user_id:
            return user_id

    # Otherwise, try API token format
    try:
        # Token format: idt:TKN-XXXX-XXXX:secret
        parts = token.split(":")
        if len(parts) >= 2 and parts[1].startswith("TKN-"):
            return parts[1]
        return None
    except Exception as e:
        logger.warning(f"Failed to parse token ID: {e}")
        return None


def normalize_token(token: str) -> str:
    """
    Normalize token for consistent cache keys and API calls.

    - Strip leading/trailing whitespace.
    - If the value starts with "Bearer " (case-insensitive), strip that prefix
      so the stored value is the raw token (e.g. idt:TKN-xxx:secret).

    This ensures the same logical token produces one cache entry and avoids
    double-prefixing when calling the Marketplace API.
    """
    if not token or not isinstance(token, str):
        return ""
    s = token.strip()
    if s.upper().startswith("BEARER "):
        s = s[7:].strip()  # len("Bearer ") = 7
    return s


async def validate_token(token: str, api_base_url: str, use_cache: bool = True) -> tuple[bool, dict | None, str | None]:
    """
    Validate an API token against the Marketplace Platform

    Calls GET /public/v1/accounts/api-tokens/{token_id}
    to verify the token is valid and active.

    Args:
        token: The API token to validate
        api_base_url: The API endpoint base URL (e.g., "https://api.platform.softwareone.com")
        use_cache: Whether to use cached validation results (default: True)

    Returns:
        Tuple of (is_valid, token_info, error_message)
        - is_valid: True if token is valid
        - token_info: Token metadata from API (if valid)
        - error_message: Error description (if invalid)

    Note:
        Token normalization (strip, strip "Bearer " prefix) is done in the HTTP server
        middleware (server.py) before the token is stored in context. This function
        assumes it receives that normalized value; it only checks for empty/None.
    """
    if not token or not isinstance(token, str) or not token.strip():
        return (False, None, "Missing or empty token")
    token = token.strip()

    cache = get_token_cache()

    # Check cache first
    if use_cache:
        cached_result = await cache.get(token, api_base_url)
        if cached_result is not None:
            is_valid, token_info = cached_result

            # Log with account info if available
            if is_valid and token_info:
                account_name = token_info.get("account", {}).get("name", "Unknown")
                account_id = token_info.get("account", {}).get("id", "Unknown")
                logger.info(f"🔐 Token validation (CACHED): ✅ Valid - {account_name} ({account_id})")
            else:
                logger.info("🔐 Token validation (CACHED): ❌ Invalid")

            return (is_valid, token_info, None if is_valid else "Token invalid (cached)")

    # Parse token ID or User ID
    token_id = parse_token_id(token)
    if not token_id:
        error = "Invalid token format. Expected: idt:TKN-XXXX-XXXX:secret or JWT token"
        logger.warning(f"❌ {error}")
        return (False, None, error)

    # Determine if this is a JWT (user ID) or API token
    is_jwt = is_jwt_token(token)

    if is_jwt and token_id.startswith("USR-"):
        # JWT token: validate via user endpoint
        user_id = token_id

        # Extract accountId from JWT claims (more reliable than API response)
        _, account_id_from_jwt = parse_jwt_claims(token)

        validation_url = f"{api_base_url.rstrip('/')}/public/v1/accounts/users/{user_id}"

        try:
            logger.info(f"🔐 Validating JWT token (user: {user_id}) against {api_base_url} (API call)...")

            async with httpx.AsyncClient(follow_redirects=True, http2=True) as client:
                response = await client.get(validation_url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=30.0)

                if response.status_code == 200:
                    user_info = response.json()

                    # Extract user information
                    user_name = user_info.get("name", "Unknown")
                    user_email = user_info.get("email", "Unknown")
                    user_status = user_info.get("status", "Unknown")

                    # Use accountId from JWT if available, otherwise try API response
                    if account_id_from_jwt:
                        account_id = account_id_from_jwt
                        # Try to get account name from API response, fallback to Unknown
                        account_name = user_info.get("account", {}).get("name", "Unknown") if isinstance(user_info.get("account"), dict) else "Unknown"
                    else:
                        # Fallback to API response if JWT doesn't have accountId
                        account_id = user_info.get("account", {}).get("id", "Unknown") if isinstance(user_info.get("account"), dict) else "Unknown"
                        account_name = user_info.get("account", {}).get("name", "Unknown") if isinstance(user_info.get("account"), dict) else "Unknown"

                    # Check if user is active
                    if user_status != "Active":
                        error = f"User exists but is not active (status: {user_status})"
                        logger.warning(f"❌ User {user_id}: {error}")

                        # Create token_info structure similar to API token format
                        token_info = {
                            "id": user_id,
                            "name": f"JWT User: {user_name}",
                            "status": user_status,
                            "account": {
                                "id": account_id,
                                "name": account_name,
                            },
                            "user": {
                                "id": user_id,
                                "name": user_name,
                                "email": user_email,
                            },
                            "type": "jwt",
                        }

                        # Cache inactive user as invalid
                        await cache.set(token, api_base_url, False, token_info)

                        return (False, token_info, error)

                    logger.info(
                        f"✅ JWT token validated successfully\n   User: {user_name} ({user_id})\n   Email: {user_email}\n   Account: {account_name} ({account_id})\n   Status: {user_status}"
                    )

                    # Create token_info structure similar to API token format
                    token_info = {
                        "id": user_id,
                        "name": f"JWT User: {user_name}",
                        "status": user_status,
                        "account": {
                            "id": account_id,
                            "name": account_name,
                        },
                        "user": {
                            "id": user_id,
                            "name": user_name,
                            "email": user_email,
                        },
                        "type": "jwt",
                    }

                    # Cache successful validation
                    await cache.set(token, api_base_url, True, token_info)

                    return (True, token_info, None)

                elif response.status_code == 401:
                    error = "JWT token authentication failed (401 Unauthorized)"
                    logger.warning(f"❌ {error}")

                    # Cache failed validation
                    await cache.set(token, api_base_url, False, None)

                    return (False, None, error)

                elif response.status_code == 404:
                    error = f"User {user_id} not found (404)"
                    logger.warning(f"❌ {error}")

                    # Cache failed validation
                    await cache.set(token, api_base_url, False, None)

                    return (False, None, error)

                else:
                    error = f"JWT token validation failed with status {response.status_code}"
                    logger.warning(f"❌ {error}")

                    # Don't cache unexpected errors (might be transient)
                    return (False, None, error)

        except httpx.TimeoutException:
            error = "JWT token validation timed out"
            logger.error(f"❌ {error}")
            # Don't cache timeouts (transient issue)
            return (False, None, error)

        except httpx.HTTPError as e:
            error = f"JWT token validation failed: {str(e)}"
            logger.error(f"❌ {error}")
            # Don't cache HTTP errors (might be transient)
            return (False, None, error)

        except Exception as e:
            error = f"Unexpected error during JWT token validation: {str(e)}"
            logger.error(f"❌ {error}")
            # Don't cache unexpected errors
            return (False, None, error)

    else:
        # API token: validate via token endpoint
        validation_url = f"{api_base_url.rstrip('/')}/public/v1/accounts/api-tokens/{token_id}"

        try:
            logger.info(f"🔐 Validating token {token_id} against {api_base_url} (API call)...")

            async with httpx.AsyncClient(follow_redirects=True, http2=True) as client:
                response = await client.get(validation_url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=30.0)

                if response.status_code == 200:
                    token_info = response.json()

                    # Extract account information for logging
                    account_id = token_info.get("account", {}).get("id", "Unknown")
                    account_name = token_info.get("account", {}).get("name", "Unknown")
                    token_name = token_info.get("name", "Unnamed Token")
                    account_type = token_info.get("account", {}).get("type", "Unknown")
                    token_status = token_info.get("status", "Unknown")

                    # Check if token is active
                    if token_status != "Active":
                        error = f"Token exists but is not active (status: {token_status})"
                        logger.warning(f"❌ Token {token_id}: {error}")

                        # Cache inactive token as invalid
                        await cache.set(token, api_base_url, False, token_info)

                        return (False, token_info, error)

                    logger.info(
                        f"✅ Token {token_id} validated successfully\n   Token Name: {token_name}\n   Account: {account_name} ({account_id})\n   Type: {account_type}\n   Status: {token_status}"
                    )

                    # Cache successful validation
                    await cache.set(token, api_base_url, True, token_info)

                    return (True, token_info, None)

                elif response.status_code == 401:
                    error = "Token authentication failed (401 Unauthorized)"
                    logger.warning(f"❌ {error}")

                    # Cache failed validation (but with shorter TTL)
                    await cache.set(token, api_base_url, False, None)

                    return (False, None, error)

                elif response.status_code == 404:
                    error = f"Token {token_id} not found (404)"
                    logger.warning(f"❌ {error}")

                    # Cache failed validation
                    await cache.set(token, api_base_url, False, None)

                    return (False, None, error)

                else:
                    error = f"Token validation failed with status {response.status_code}"
                    logger.warning(f"❌ {error}")

                    # Don't cache unexpected errors (might be transient)
                    return (False, None, error)

        except httpx.TimeoutException:
            error = "Token validation timed out"
            logger.error(f"❌ {error}")
            # Don't cache timeouts (transient issue)
            return (False, None, error)

        except httpx.HTTPError as e:
            error = f"Token validation failed: {str(e)}"
            logger.error(f"❌ {error}")
            # Don't cache HTTP errors (might be transient)
            return (False, None, error)

        except Exception as e:
            error = f"Unexpected error during token validation: {str(e)}"
            logger.error(f"❌ {error}")
            # Don't cache unexpected errors
            return (False, None, error)


async def validate_token_for_resources(token: str, api_base_url: str) -> tuple[bool, str | None]:
    """
    Validate token for resource access (simplified interface)

    Args:
        token: The API token
        api_base_url: The API endpoint base URL

    Returns:
        Tuple of (is_valid, error_message)
    """
    is_valid, token_info, error = await validate_token(token, api_base_url)
    return (is_valid, error)
