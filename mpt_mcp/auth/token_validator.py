import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from fastmcp.server.lifespan import lifespan

from mpt_mcp.auth.jwt_verifier import INVALID_JWT_ERROR, JwtVerifier
from mpt_mcp.auth.token_cache import TokenValidationCache
from mpt_mcp.auth.tokens import is_jwt_token, parse_token_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ACTIVE_STATUS = "Active"
HTTP_TIMEOUT = 30.0
JWKS_URL_REQUIRED_ERROR = (
    "JWT verification required. Set JWT_JWKS_URL or use a token with iss claim (e.g. Auth0)."
)
VALIDATOR_KEY = "token_validator"
UNKNOWN = "Unknown"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenValidation:
    """Result of validating a token: whether it is valid, its metadata and why it is not."""

    is_valid: bool
    token_info: dict[str, Any] | None = None
    error: str | None = None

    @property
    def account(self) -> dict[str, Any]:
        """Return the account of the token, or {} when its metadata has none."""
        account = (self.token_info or {}).get("account")
        return account if isinstance(account, dict) else {}


@dataclass(frozen=True)
class TokenCheck:
    """Marketplace API request that checks a token, and the wording of its errors."""

    token: str
    api_base_url: str
    url: str
    # Token or JWT token, for the error messages
    label: str
    # Token TKN-… or User USR-…, for the not found error
    subject: str


class TokenValidator:
    """Validates API tokens and JWTs against the Marketplace API, caching the results."""

    def __init__(
        self,
        cache: TokenValidationCache | None = None,
        jwt_verifier: JwtVerifier | None = None,
    ) -> None:
        self.cache = cache or TokenValidationCache(ttl_minutes=10)
        self.jwt_verifier = jwt_verifier or JwtVerifier()

    async def validate(
        self, token: str, api_base_url: str, *, use_cache: bool = True
    ) -> TokenValidation:
        """
        Validate a token against the Marketplace API of an endpoint.

        API tokens (idt:TKN-…) are checked with GET /public/v1/accounts/api-tokens/{id}; JWTs
        are verified with their issuer's JWKS, then their user is checked with
        GET /public/v1/accounts/users/{id}. Valid and rejected tokens are cached; failures that
        may be transient (timeouts, unexpected statuses or responses) are not.

        Args:
            token: Normalized token, without the Bearer prefix
            api_base_url: Base URL of the endpoint, e.g. https://api.platform.softwareone.com
            use_cache: Use a cached result when there is one

        Returns:
            Whether the token is valid, its metadata from the API and the error when it is not
        """
        if not token or not token.strip():
            return TokenValidation(is_valid=False, error="Missing or empty token")

        token = token.strip()
        if use_cache:
            cached_result = await self.cache.get(token, api_base_url)
            if cached_result is not None:
                return self._read_cached(cached_result)

        if is_jwt_token(token):
            return await self._validate_jwt(token, api_base_url)

        token_id = parse_token_id(token)
        if not token_id:
            return reject("Invalid token format. Expected: idt:TKN-XXXX-XXXX:secret or JWT token")

        return await self._validate_api_token(token, api_base_url, token_id)

    async def _fetch(self, check: TokenCheck) -> dict[str, Any] | TokenValidation:
        logger.info("Validating %s against %s (API call)...", check.subject, check.api_base_url)
        timeout_config = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_TIMEOUT)
        headers = {"Authorization": f"Bearer {check.token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, http2=True, timeout=timeout_config
            ) as client:
                response = await client.get(check.url, headers=headers)
        except httpx.TimeoutException:
            logger.exception("%s validation timed out", check.label)
            return TokenValidation(is_valid=False, error=f"{check.label} validation timed out")
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            logger.exception("%s validation failed", check.label)
            return TokenValidation(
                is_valid=False, error=f"{check.label} validation failed: {error!s}"
            )
        except ValueError as error:
            # A token httpx cannot send in a header
            label = check.label.lower()
            logger.exception("Unexpected error during %s validation", label)
            return TokenValidation(
                is_valid=False, error=f"Unexpected error during {label} validation: {error!s}"
            )

        return await self._read_response(check, response)

    async def _read_response(
        self, check: TokenCheck, response: httpx.Response
    ) -> dict[str, Any] | TokenValidation:
        status_code = response.status_code
        if status_code == HTTPStatus.OK:
            try:
                response_body = response.json()
            except ValueError:
                response_body = None
            if isinstance(response_body, dict):
                return response_body
            return reject(f"{check.label} validation returned an unexpected response")

        if status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND}:
            await self.cache.set(check.token, check.api_base_url, is_valid=False, token_info=None)
            if status_code == HTTPStatus.UNAUTHORIZED:
                return reject(f"{check.label} authentication failed (401 Unauthorized)")
            return reject(f"{check.subject} not found (404)")

        return reject(f"{check.label} validation failed with status {status_code}")

    def _read_cached(self, cached_result: tuple[bool, dict[str, Any] | None]) -> TokenValidation:
        is_valid, token_info = cached_result
        validation = TokenValidation(
            is_valid=is_valid,
            token_info=token_info,
            error=None if is_valid else "Token invalid (cached)",
        )
        if is_valid and token_info:
            logger.info(
                "Token validation (CACHED): Valid - %s (%s)",
                validation.account.get("name", UNKNOWN),
                validation.account.get("id", UNKNOWN),
            )
        else:
            logger.info("Token validation (CACHED): Invalid")
        return validation

    async def _validate_api_token(
        self, token: str, api_base_url: str, token_id: str
    ) -> TokenValidation:
        check = TokenCheck(
            token=token,
            api_base_url=api_base_url,
            url=f"{api_base_url.rstrip('/')}/public/v1/accounts/api-tokens/{token_id}",
            label="Token",
            subject=f"Token {token_id}",
        )
        token_info = await self._fetch(check)
        if isinstance(token_info, TokenValidation):
            return token_info

        validation = TokenValidation(is_valid=True, token_info=token_info)
        token_status = token_info.get("status", UNKNOWN)
        if token_status != ACTIVE_STATUS:
            await self.cache.set(token, api_base_url, is_valid=False, token_info=token_info)
            return reject(f"Token exists but is not active (status: {token_status})", token_info)

        logger.info(
            "Token %s validated: account %s (%s), type %s, status %s",
            token_id,
            validation.account.get("name", UNKNOWN),
            validation.account.get("id", UNKNOWN),
            validation.account.get("type", UNKNOWN),
            token_status,
        )
        await self.cache.set(token, api_base_url, is_valid=True, token_info=token_info)
        return validation

    async def _validate_jwt(self, token: str, api_base_url: str) -> TokenValidation:
        jwks_url = self.jwt_verifier.find_jwks_url(token)
        payload, verify_error = (
            await self.jwt_verifier.verify(token, jwks_url)
            if jwks_url
            else (None, JWKS_URL_REQUIRED_ERROR)
        )
        if payload is None:
            return reject(verify_error or INVALID_JWT_ERROR)

        user_id, account_id = self.jwt_verifier.extract_claims(payload)
        if not user_id:
            return reject("JWT missing or invalid userId claim")

        check = TokenCheck(
            token=token,
            api_base_url=api_base_url,
            url=f"{api_base_url.rstrip('/')}/public/v1/accounts/users/{user_id}",
            label="JWT token",
            subject=f"User {user_id}",
        )
        user_info = await self._fetch(check)
        if isinstance(user_info, TokenValidation):
            return user_info

        token_info = build_jwt_token_info(user_id, account_id, user_info)
        user_status = token_info["status"]
        if user_status != ACTIVE_STATUS:
            await self.cache.set(token, api_base_url, is_valid=False, token_info=token_info)
            return reject(f"User exists but is not active (status: {user_status})", token_info)

        logger.info(
            "JWT token validated: user %s (%s), account %s (%s), status %s",
            token_info["user"]["name"],
            user_id,
            token_info["account"]["name"],
            token_info["account"]["id"],
            user_status,
        )
        await self.cache.set(token, api_base_url, is_valid=True, token_info=token_info)
        return TokenValidation(is_valid=True, token_info=token_info)


def build_jwt_token_info(
    user_id: str, account_id: str | None, user_info: dict[str, Any]
) -> dict[str, Any]:
    """
    Build the token metadata of a JWT from its user, as the API token endpoint returns it.

    Args:
        user_id: User ID from the JWT claims
        account_id: Account ID from the JWT claims, or None to take the user's account
        user_info: User from GET /public/v1/accounts/users/{id}

    Returns:
        Token metadata with the user's id, name, status, account and user
    """
    user_account = user_info.get("account")
    account = user_account if isinstance(user_account, dict) else {}
    user_name = user_info.get("name", UNKNOWN)
    return {
        "id": user_id,
        "name": f"JWT User: {user_name}",
        "status": user_info.get("status", UNKNOWN),
        "account": {
            "id": account_id or account.get("id", UNKNOWN),
            "name": account.get("name", UNKNOWN),
        },
        "user": {"id": user_id, "name": user_name, "email": user_info.get("email", UNKNOWN)},
        "type": "jwt",
    }


def reject(error: str, token_info: dict[str, Any] | None = None) -> TokenValidation:
    """
    Log why a token is rejected and return the rejection.

    Args:
        error: Why the token is not valid
        token_info: Token metadata, when the API returned it

    Returns:
        Invalid token validation with the error
    """
    logger.warning("%s", error)
    return TokenValidation(is_valid=False, token_info=token_info, error=error)


def get_token_validator(
    context: Context = CurrentContext(),  # noqa: WPS404
) -> TokenValidator:
    """
    Return the token validator of the server, created by token_lifespan.

    Args:
        context: Context of the MCP request, injected by FastMCP

    Returns:
        Token validator, with its validation and JWKS caches
    """
    token_validator: TokenValidator = context.lifespan_context[VALIDATOR_KEY]
    return token_validator


@lifespan
async def token_lifespan(server: Any) -> AsyncIterator[dict[str, Any]]:  # ruff: ignore[unused-async]
    """Give the server a token validator with empty validation and JWKS caches."""
    yield {VALIDATOR_KEY: TokenValidator()}
