import asyncio
import base64
import datetime as dt
import hashlib
import json
import logging
from http import HTTPStatus
from typing import Any

import httpx
import jwt

from mpt_mcp.config import config

ACTIVE_STATUS = "Active"

DEFAULT_JWT_EXP_LEEWAY_SECONDS = 120

HTTP_TIMEOUT = 30.0
# Algorithms we accept for JWT signature verification (never trust token's alg header alone)
JWT_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

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
    combined = f"{token}|{api_base_url}"
    return hashlib.sha256(combined.encode()).hexdigest()


class TokenValidationCache:
    """
    In-memory cache for token validations with TTL.

    Caches token validation results to avoid repeated API calls.
    Cache entries expire after a configurable TTL.

    SECURITY: Uses SHA256 hash of token+endpoint as cache key instead of
    storing full tokens in memory. This prevents token exposure if memory is dumped.
    """

    def __init__(self, ttl_minutes: int = 10):
        """
        Initialize token validation cache.

        Args:
            ttl_minutes: Time-to-live for cache entries in minutes (default: 10)
        """
        self.ttl = dt.timedelta(minutes=ttl_minutes)
        # SECURITY: Keys are SHA256 hashes of token+endpoint, not raw tokens
        self._cache: dict[str, tuple[bool, dt.datetime, dict[str, Any] | None]] = {}
        self._lock = asyncio.Lock()
        logger.info(
            "🔐 Token validation cache initialized (TTL: %sm, secure hash keys)", ttl_minutes
        )

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
        cache_key = _hash_token(token, api_base_url)

        async with self._lock:
            if cache_key in self._cache:
                is_valid, expiry, token_info = self._cache[cache_key]

                if dt.datetime.now() < expiry:
                    logger.debug(
                        "✅ Token validation cache hit (expires in %ss)",
                        (expiry - dt.datetime.now()).seconds,
                    )
                    return (is_valid, token_info)
                logger.debug("⏰ Token validation cache expired, removing")
                del self._cache[cache_key]

            return None

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
        cache_key = _hash_token(token, api_base_url)

        async with self._lock:
            expiry = dt.datetime.now() + self.ttl
            self._cache[cache_key] = (is_valid, expiry, token_info)
            logger.debug(
                "💾 Cached token validation (valid=%s, expires in %ss)", is_valid, self.ttl.seconds
            )

    async def invalidate(self, token: str, api_base_url: str) -> None:
        """
        Invalidate a specific token in the cache.

        Args:
            token: The API token to invalidate
            api_base_url: The API endpoint
        """
        cache_key = _hash_token(token, api_base_url)

        async with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.debug("🗑️  Invalidated token from cache")

    async def clear(self) -> None:
        """Clear all cached validations."""
        async with self._lock:
            self._cache.clear()
            logger.info("🗑️  Cleared all token validation cache")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        now = dt.datetime.now()
        expiries = [expiry for _, expiry, _ in self._cache.values()]
        valid_count = sum(1 for expiry in expiries if expiry > now)
        expired_count = len(self._cache) - valid_count

        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "ttl_minutes": self.ttl.total_seconds() / 60,
        }


# Global token validation cache
_token_cache: TokenValidationCache | None = None


def get_token_cache(ttl_minutes: int = 10) -> TokenValidationCache:
    """Get or create the global token validation cache."""
    global _token_cache

    if _token_cache is None:
        _token_cache = TokenValidationCache(ttl_minutes=ttl_minutes)

    return _token_cache


# JWKS cache for JWT signature verification (url -> (jwks_dict, expiry))
_jwks_cache: dict[str, tuple[dict[str, Any], dt.datetime]] = {}
_jwks_cache_ttl = dt.timedelta(minutes=60)
_jwks_lock = asyncio.Lock()


async def _fetch_jwks_cached(jwks_url: str) -> dict[str, Any] | None:
    """
    Fetch JWKS from URL with in-memory cache (TTL 1 hour).

    Returns:
        JWKS dict with "keys" list, or None on fetch/parse error.
    """
    async with _jwks_lock:
        if jwks_url in _jwks_cache:
            jwks_dict, expiry = _jwks_cache[jwks_url]
            if dt.datetime.now() < expiry:
                return jwks_dict
            del _jwks_cache[jwks_url]

    try:
        # 30s connect and default for JWKS fetch
        timeout_config = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_TIMEOUT)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_config) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks_dict = response.json()
    except Exception as error:
        logger.warning("Failed to fetch JWKS from %s: %s", jwks_url, error)
        return None

    if not isinstance(jwks_dict, dict) or "keys" not in jwks_dict:
        logger.warning("Invalid JWKS format from %s", jwks_url)
        return None

    async with _jwks_lock:
        _jwks_cache[jwks_url] = (jwks_dict, dt.datetime.now() + _jwks_cache_ttl)

    return jwks_dict


def _extract_claims_from_payload(
    payload: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Extract userId and accountId from SoftwareOne JWT payload."""
    raw_user_id = payload.get("https://claims.softwareone.com/userId")
    user_id = (
        raw_user_id
        if raw_user_id and isinstance(raw_user_id, str) and raw_user_id.startswith("USR-")
        else None
    )
    raw_account_id = payload.get("https://claims.softwareone.com/accountId")
    account_id = (
        raw_account_id
        if raw_account_id and isinstance(raw_account_id, str) and raw_account_id.startswith("ACC-")
        else None
    )
    return (user_id, account_id)


def _get_signing_keys(token: str, jwks_dict: dict[str, Any]) -> list[jwt.PyJWK]:
    """
    Select the JWKS keys that may have signed the token.

    Uses the key matching the token's ``kid`` header, or every key in the set when the
    token has no ``kid``.

    Raises:
        jwt.PyJWTError: If the JWKS has no usable keys or no key matches the ``kid``.
    """
    jwk_set = jwt.PyJWKSet.from_dict(jwks_dict)
    kid = jwt.get_unverified_header(token).get("kid")
    if kid is None:
        return list(jwk_set.keys)
    try:
        return [jwk_set[kid]]
    except KeyError:
        raise jwt.InvalidKeyError(f"No JWKS key matches kid {kid!r}") from None


async def _verify_jwt_and_get_payload(
    token: str, jwks_url: str
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Verify JWT signature using JWKS and return the payload.

    Uses explicit algorithm list (no alg:none). Validates exp and nbf with leeway (clock skew).

    Returns:
        (payload, error_message). On success: (payload_dict, None). On failure:
        (None, "Token expired") or (None, "JWT signature or claims invalid").
        If JWKS fetch failed: (None, None).
    """
    jwks_dict = await _fetch_jwks_cached(jwks_url)
    if not jwks_dict:
        return (None, None)

    leeway = getattr(config, "jwt_exp_leeway_seconds", DEFAULT_JWT_EXP_LEEWAY_SECONDS) or 0

    try:
        last_error: jwt.PyJWTError = jwt.InvalidKeyError("JWKS has no signing keys")
        for signing_key in _get_signing_keys(token, jwks_dict):
            try:
                payload = jwt.decode(
                    token,
                    signing_key,
                    algorithms=JWT_ALGORITHMS,
                    leeway=leeway,
                    options={"verify_aud": False, "verify_iss": False},
                )
            except jwt.InvalidSignatureError as error:
                last_error = error
                continue
            return (payload, None)
        raise last_error
    except jwt.ExpiredSignatureError as error:
        logger.debug("JWT verification failed (expired, leeway=%ss): %s", leeway, error)
        return (None, "Token expired")
    except jwt.PyJWTError as error:
        logger.debug("JWT verification failed: %s", error)
        return (None, "JWT signature or claims invalid")


def is_jwt_token(token: str) -> bool:
    """
    Check if a token is a JWT (JSON Web Token).

    JWT format: header.payload.signature (3 parts separated by dots)

    Args:
        token: The token string to check

    Returns:
        True if token appears to be a JWT, False otherwise
    """
    if not token or not isinstance(token, str):
        return False

    parts = token.split(".")
    return len(parts) == 3


def _get_jwks_url_from_token(token: str) -> str | None:
    """
    Derive JWKS URL from the token's issuer (iss) claim.

    Standard for OIDC/Auth0: {issuer}/.well-known/jwks.json
    We only read the payload segment to get iss for the URL; the token is verified
    afterward via JWKS in _verify_jwt_and_get_payload (we do not trust claims here).
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Decode payload segment (base64url); no JWT verify API used—only parsing for iss
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
        iss = payload.get("iss")
        if not iss or not isinstance(iss, str):
            return None
        iss = iss.strip().rstrip("/")
        if not iss.startswith("https://"):
            return None
        return f"{iss}/.well-known/jwks.json"
    except Exception:
        return None


def parse_jwt_claims(token: str) -> tuple[str | None, str | None]:
    """
    Parse user ID and account ID from a JWT token.

    We do not decode without verification. JWTs are verified in validate_token()
    via JWKS (from JWT_JWKS_URL or derived from the token's iss claim, e.g. Auth0).
    This returns (None, None) so callers do not trust unverified claims.
    """
    return (None, None)


def parse_token_id(token: str) -> str | None:
    """
    Parse token ID from a token string.

    Supports: API Token idt:TKN-XXXX-XXXX:secret_part (returns TKN-...).
    For JWT we do not decode without verification; validate_token() verifies via JWKS
    and extracts the user ID. This returns None for JWT.
    """
    if is_jwt_token(token):
        return None

    try:
        # idt:TKN-XXXX-XXXX:secret
        parts = token.split(":")
        if len(parts) >= 2 and parts[1].startswith("TKN-"):
            return parts[1]
        return None
    except Exception as error:
        logger.warning("Failed to parse token ID: %s", error)
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
    normalized = token.strip()
    if normalized.upper().startswith("BEARER "):
        normalized = normalized[7:].strip()
    return normalized


async def validate_token(
    token: str, api_base_url: str, *, use_cache: bool = True
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """
    Validate an API token against the Marketplace Platform.

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

    if use_cache:
        cached_result = await cache.get(token, api_base_url)
        if cached_result is not None:
            is_valid, token_info = cached_result

            if is_valid and token_info:
                account_name = token_info.get("account", {}).get("name", "Unknown")
                account_id = token_info.get("account", {}).get("id", "Unknown")
                logger.info(
                    "🔐 Token validation (CACHED): ✅ Valid - %s (%s)", account_name, account_id
                )
            else:
                logger.info("🔐 Token validation (CACHED): ❌ Invalid")

            return (is_valid, token_info, None if is_valid else "Token invalid (cached)")

    # JWT path: verify with JWKS when URL is set or can be derived from token's iss claim (e.g.
    # Auth0)
    is_jwt = is_jwt_token(token)
    account_id_from_jwt: str | None = None

    if is_jwt:
        jwks_url = config.jwt_jwks_url or _get_jwks_url_from_token(token)
        if not jwks_url:
            error = (
                "JWT verification required. Set JWT_JWKS_URL or use a token with iss claim (e.g. "
                "Auth0)."
            )
            logger.warning("❌ %s", error)
            return (False, None, error)
        payload, verify_error = await _verify_jwt_and_get_payload(token, jwks_url)
        if payload is None:
            error = verify_error or "JWT signature or claims invalid"
            logger.warning("❌ %s", error)
            return (False, None, error)
        user_id, account_id_from_jwt = _extract_claims_from_payload(payload)
        if not user_id or not user_id.startswith("USR-"):
            error = "JWT missing or invalid userId claim"
            logger.warning("❌ %s", error)
            return (False, None, error)
        token_id = user_id
    else:
        token_id = parse_token_id(token)

    if not token_id:
        error = "Invalid token format. Expected: idt:TKN-XXXX-XXXX:secret or JWT token"
        logger.warning("❌ %s", error)
        return (False, None, error)

    if is_jwt and token_id.startswith("USR-"):
        # JWT token: already verified; validate via user endpoint for status/account info
        user_id = token_id

        validation_url = f"{api_base_url.rstrip('/')}/public/v1/accounts/users/{user_id}"

        try:
            logger.info(
                "🔐 Validating JWT token (user: %s) against %s (API call)...", user_id, api_base_url
            )

            timeout_config = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_TIMEOUT)
            async with httpx.AsyncClient(
                follow_redirects=True, http2=True, timeout=timeout_config
            ) as client:
                response = await client.get(
                    validation_url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )

                if response.status_code == HTTPStatus.OK:
                    user_info = response.json()

                    # Extract user information
                    user_name = user_info.get("name", "Unknown")
                    user_email = user_info.get("email", "Unknown")
                    user_status = user_info.get("status", "Unknown")

                    # Use accountId from JWT if available, otherwise try API response
                    if account_id_from_jwt:
                        account_id = account_id_from_jwt
                        # Try to get account name from API response, fallback to Unknown
                        account_name = (
                            user_info.get("account", {}).get("name", "Unknown")
                            if isinstance(user_info.get("account"), dict)
                            else "Unknown"
                        )
                    else:
                        # Fallback to API response if JWT doesn't have accountId
                        account_id = (
                            user_info.get("account", {}).get("id", "Unknown")
                            if isinstance(user_info.get("account"), dict)
                            else "Unknown"
                        )
                        account_name = (
                            user_info.get("account", {}).get("name", "Unknown")
                            if isinstance(user_info.get("account"), dict)
                            else "Unknown"
                        )

                    # Check if user is active
                    if user_status != ACTIVE_STATUS:
                        error = f"User exists but is not active (status: {user_status})"
                        logger.warning("❌ User %s: %s", user_id, error)

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
                        await cache.set(token, api_base_url, is_valid=False, token_info=token_info)

                        return (False, token_info, error)

                    logger.info(
                        "✅ JWT token validated successfully\n   User: %s (%s)\n   Email: %s\n   "
                        "Account: %s (%s)\n   Status: %s",
                        user_name,
                        user_id,
                        user_email,
                        account_name,
                        account_id,
                        user_status,
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
                    await cache.set(token, api_base_url, is_valid=True, token_info=token_info)

                    return (True, token_info, None)

                if response.status_code == HTTPStatus.UNAUTHORIZED:
                    error = "JWT token authentication failed (401 Unauthorized)"
                    logger.warning("❌ %s", error)

                    # Cache failed validation
                    await cache.set(token, api_base_url, is_valid=False, token_info=None)

                    return (False, None, error)

                if response.status_code == HTTPStatus.NOT_FOUND:
                    error = f"User {user_id} not found (404)"
                    logger.warning("❌ %s", error)

                    # Cache failed validation
                    await cache.set(token, api_base_url, is_valid=False, token_info=None)

                    return (False, None, error)

                error = f"JWT token validation failed with status {response.status_code}"
                logger.warning("❌ %s", error)

                # Don't cache unexpected errors (might be transient)
                return (False, None, error)

        except httpx.TimeoutException:
            error = "JWT token validation timed out"
            logger.exception("❌ %s", error)
            # Don't cache timeouts (transient issue)
            return (False, None, error)

        except httpx.HTTPError as http_error:
            error = f"JWT token validation failed: {http_error!s}"
            logger.exception("❌ %s", error)
            # Don't cache HTTP errors (might be transient)
            return (False, None, error)

        except Exception as unexpected_error:
            error = f"Unexpected error during JWT token validation: {unexpected_error!s}"
            logger.exception("❌ %s", error)
            # Don't cache unexpected errors
            return (False, None, error)

    else:
        # API token: validate via token endpoint
        validation_url = f"{api_base_url.rstrip('/')}/public/v1/accounts/api-tokens/{token_id}"

        try:
            logger.info("🔐 Validating token %s against %s (API call)...", token_id, api_base_url)

            timeout_config = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_TIMEOUT)
            async with httpx.AsyncClient(
                follow_redirects=True, http2=True, timeout=timeout_config
            ) as client:
                response = await client.get(
                    validation_url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )

                if response.status_code == HTTPStatus.OK:
                    token_info = response.json()

                    # Extract account information for logging
                    account_id = token_info.get("account", {}).get("id", "Unknown")
                    account_name = token_info.get("account", {}).get("name", "Unknown")
                    token_name = token_info.get("name", "Unnamed Token")
                    account_type = token_info.get("account", {}).get("type", "Unknown")
                    token_status = token_info.get("status", "Unknown")

                    # Check if token is active
                    if token_status != ACTIVE_STATUS:
                        error = f"Token exists but is not active (status: {token_status})"
                        logger.warning("❌ Token %s: %s", token_id, error)

                        # Cache inactive token as invalid
                        await cache.set(token, api_base_url, is_valid=False, token_info=token_info)

                        return (False, token_info, error)

                    logger.info(
                        "✅ Token %s validated successfully\n   Token Name: %s\n   Account: %s "
                        "(%s)\n   Type: %s\n   Status: %s",
                        token_id,
                        token_name,
                        account_name,
                        account_id,
                        account_type,
                        token_status,
                    )

                    # Cache successful validation
                    await cache.set(token, api_base_url, is_valid=True, token_info=token_info)

                    return (True, token_info, None)

                if response.status_code == HTTPStatus.UNAUTHORIZED:
                    error = "Token authentication failed (401 Unauthorized)"
                    logger.warning("❌ %s", error)

                    # Cache failed validation (but with shorter TTL)
                    await cache.set(token, api_base_url, is_valid=False, token_info=None)

                    return (False, None, error)

                if response.status_code == HTTPStatus.NOT_FOUND:
                    error = f"Token {token_id} not found (404)"
                    logger.warning("❌ %s", error)

                    # Cache failed validation
                    await cache.set(token, api_base_url, is_valid=False, token_info=None)

                    return (False, None, error)

                error = f"Token validation failed with status {response.status_code}"
                logger.warning("❌ %s", error)

                # Don't cache unexpected errors (might be transient)
                return (False, None, error)

        except httpx.TimeoutException:
            error = "Token validation timed out"
            logger.exception("❌ %s", error)
            # Don't cache timeouts (transient issue)
            return (False, None, error)

        except httpx.HTTPError as http_error:
            error = f"Token validation failed: {http_error!s}"
            logger.exception("❌ %s", error)
            # Don't cache HTTP errors (might be transient)
            return (False, None, error)

        except Exception as unexpected_error:
            error = f"Unexpected error during token validation: {unexpected_error!s}"
            logger.exception("❌ %s", error)
            # Don't cache unexpected errors
            return (False, None, error)
