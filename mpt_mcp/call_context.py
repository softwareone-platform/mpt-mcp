from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastmcp.server.dependencies import get_http_request

from mpt_mcp.api_client import APIClient, normalize_endpoint_url
from mpt_mcp.config import config
from mpt_mcp.token_validator import normalize_token, parse_token_id, validate_token

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

NO_CREDENTIALS_ERROR = (
    "Missing API token. Please provide your API token in the X-MPT-Authorization header (HTTP) "
    "or in MARKETPLACE_API_TOKEN (stdio)."
)
TRUTHY_HEADER_VALUES = ("1", "true", "yes")


@dataclass(frozen=True)
class CallContext:
    """Marketplace API credentials sent by the caller of the current MCP request."""

    endpoint: str
    token: str | None
    validate_fresh: bool = False

    @property
    def user_id(self) -> str | None:
        """Token ID (TKN-XXXX-XXXX) of an API token, or None for a missing token or a JWT."""
        return parse_token_id(self.token) if self.token else None

    async def create_api_client(self) -> APIClient:
        """
        Create an API client for the caller's endpoint after validating the caller's token.

        Returns:
            API client authenticated with the caller's token

        Raises:
            ValueError: If the token is missing or fails validation
        """
        if not self.token:
            raise ValueError(NO_CREDENTIALS_ERROR)

        await self._validate_token()

        return APIClient(base_url=self.endpoint, token=self.token)

    async def _validate_token(self) -> None:
        is_valid, token_info, error = await validate_token(
            self.token, self.endpoint, use_cache=not self.validate_fresh
        )
        if not is_valid:
            logger.warning("Token validation failed: %s", error)
            raise ValueError(
                f"Token validation failed: {error}. Please ensure your API token is valid and "
                "active."
            )

        account = (token_info or {}).get("account", {})
        logger.info(
            "Token validated for %s - Account: %s (%s)",
            self.endpoint,
            account.get("name", "Unknown"),
            account.get("id", "Unknown"),
        )


def get_call_context() -> CallContext:
    """
    Build the call context of the current MCP request.

    The HTTP server reads it from the request headers; the stdio server, which has no request,
    from MARKETPLACE_API_BASE_URL and MARKETPLACE_API_TOKEN.

    Returns:
        Call context with the caller's endpoint, token and validation preference
    """
    try:
        request = get_http_request()
    except RuntimeError:
        token = config.marketplace_api_token
        return CallContext(
            endpoint=normalize_endpoint_url(config.marketplace_api_base_url),
            token=normalize_token(token) if token else None,
        )

    return read_call_context(request)


def read_call_context(request: Request) -> CallContext:
    """
    Build the call context from the X-MPT-* headers of an HTTP request.

    Args:
        request: HTTP request of the MCP call

    Returns:
        Call context with the caller's endpoint, token and validation preference
    """
    raw_token = request.headers.get("x-mpt-authorization")
    endpoint = request.headers.get("x-mpt-endpoint") or config.http_default_base_url
    validate_fresh = (
        request.headers.get("x-mpt-validate-fresh", "").strip().lower() in TRUTHY_HEADER_VALUES
    )
    return CallContext(
        endpoint=normalize_endpoint_url(endpoint),
        token=normalize_token(raw_token) if raw_token else None,
        validate_fresh=validate_fresh,
    )
