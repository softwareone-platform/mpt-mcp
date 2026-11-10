import asyncio
import base64
import datetime as dt
import json
import logging
from typing import Any

import httpx
import jwt

from mpt_mcp.auth.tokens import JWT_PART_COUNT
from mpt_mcp.config import config

CLAIMS_NAMESPACE = "https://claims.softwareone.com"
HTTP_TIMEOUT = 30.0
INVALID_JWT_ERROR = "JWT signature or claims invalid"
JWKS_TTL = dt.timedelta(minutes=60)
# Algorithms we accept for JWT signature verification (never trust token's alg header alone)
JWT_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")

logger = logging.getLogger(__name__)

type CachedJwks = tuple[dict[str, Any], dt.datetime]
type ClaimIds = tuple[str | None, str | None]
type JwtVerification = tuple[dict[str, Any] | None, str | None]


class JwtVerifier:
    """Verifies JWT signatures with the issuer's JWKS, kept in memory for an hour."""

    def __init__(self) -> None:
        # JWKS by URL, with the time it expires
        self._jwks: dict[str, CachedJwks] = {}
        self._lock = asyncio.Lock()

    def extract_claims(self, payload: dict[str, Any]) -> ClaimIds:
        """
        Read the SoftwareOne user and account IDs of a verified JWT payload.

        Args:
            payload: Verified JWT payload

        Returns:
            (user_id, account_id), each None when the claim is missing or is not a USR-/ACC- ID
        """
        user_id = payload.get(f"{CLAIMS_NAMESPACE}/userId")
        account_id = payload.get(f"{CLAIMS_NAMESPACE}/accountId")
        return (
            user_id if isinstance(user_id, str) and user_id.startswith("USR-") else None,
            account_id if isinstance(account_id, str) and account_id.startswith("ACC-") else None,
        )

    def find_jwks_url(self, token: str) -> str | None:
        """
        Return the configured JWKS URL, or the one of the token's issuer.

        The issuer URL follows OIDC: {iss}/.well-known/jwks.json. The iss claim is read
        without verifying the token, which verify() does afterwards with that JWKS.

        Args:
            token: JWT to verify

        Returns:
            JWKS URL, or None when none is configured and the token has no https iss claim
        """
        if config.jwt_jwks_url:
            return config.jwt_jwks_url

        parts = token.split(".")
        if len(parts) != JWT_PART_COUNT:
            return None

        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        except ValueError:  # binascii.Error and UnicodeDecodeError are ValueErrors too
            return None

        iss = payload.get("iss") if isinstance(payload, dict) else None
        if not isinstance(iss, str) or not iss.strip().startswith("https://"):
            return None

        iss = iss.strip().rstrip("/")
        return f"{iss}/.well-known/jwks.json"

    async def load_jwks(self, jwks_url: str) -> dict[str, Any] | None:
        """
        Return the JWKS at a URL, fetched again after an hour.

        Args:
            jwks_url: URL of the issuer's JWKS

        Returns:
            JWKS with its "keys" list, or None when it cannot be fetched or read
        """
        async with self._lock:
            cached_jwks = self._jwks.get(jwks_url)
            if cached_jwks is not None:
                jwks_dict, expiry = cached_jwks
                if dt.datetime.now(dt.UTC) < expiry:
                    return jwks_dict

                self._jwks.pop(jwks_url)

        timeout_config = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_TIMEOUT)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_config) as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            logger.warning("Failed to fetch JWKS from %s: %s", jwks_url, error)
            return None

        try:
            jwks_dict = response.json()
        except ValueError as error:
            logger.warning("Invalid JWKS format from %s: %s", jwks_url, error)
            return None

        if not isinstance(jwks_dict, dict) or "keys" not in jwks_dict:
            logger.warning("Invalid JWKS format from %s", jwks_url)
            return None

        expiry = dt.datetime.now(dt.UTC) + JWKS_TTL
        async with self._lock:
            self._jwks[jwks_url] = (jwks_dict, expiry)

        return jwks_dict

    async def verify(self, token: str, jwks_url: str) -> JwtVerification:
        """
        Verify the signature of a JWT with the JWKS and return its payload.

        Args:
            token: JWT to verify
            jwks_url: URL of the issuer's JWKS

        Returns:
            (payload, None) when the token is valid, (None, error) when it is expired or its
            signature or claims are invalid, and (None, None) when the JWKS could not be fetched
        """
        jwks_dict = await self.load_jwks(jwks_url)
        if not jwks_dict:
            return (None, None)

        try:
            signing_keys = self._select_signing_keys(token, jwks_dict)
        except jwt.PyJWTError as error:
            logger.debug("No JWKS key to verify the JWT: %s", error)
            return (None, INVALID_JWT_ERROR)

        for signing_key in signing_keys:
            verification = self._decode(token, signing_key)
            if verification is not None:
                return verification

        logger.debug("No JWKS key matches the JWT signature")
        return (None, INVALID_JWT_ERROR)

    def _decode(self, token: str, signing_key: jwt.PyJWK) -> JwtVerification | None:
        # Explicit algorithms (no alg:none); exp and nbf allow the configured clock skew
        leeway = config.jwt_exp_leeway_seconds
        try:
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=JWT_ALGORITHMS,
                leeway=leeway,
                options={"verify_aud": False, "verify_iss": False},
            )
        except jwt.InvalidSignatureError:
            return None
        except jwt.ExpiredSignatureError as error:
            logger.debug("JWT verification failed (expired, leeway=%ss): %s", leeway, error)
            return (None, "Token expired")
        except jwt.PyJWTError as error:
            logger.debug("JWT verification failed: %s", error)
            return (None, INVALID_JWT_ERROR)

        return (payload, None)

    def _select_signing_keys(self, token: str, jwks_dict: dict[str, Any]) -> list[jwt.PyJWK]:
        # The key of the token's kid header, or every key when the token has no kid
        jwk_set = jwt.PyJWKSet.from_dict(jwks_dict)
        kid = jwt.get_unverified_header(token).get("kid")
        if kid is None:
            return list(jwk_set.keys)

        try:
            return [jwk_set[kid]]
        except KeyError:
            raise jwt.InvalidKeyError(f"No JWKS key matches kid {kid!r}") from None
