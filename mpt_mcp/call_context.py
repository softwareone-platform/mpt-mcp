from dataclasses import dataclass

from fastmcp.dependencies import CurrentRequest

# FastMCP resolves dependency annotations at runtime, so Request cannot be a TYPE_CHECKING import
from starlette.requests import Request  # noqa: TC002

from mpt_mcp.api_client import APIClient
from mpt_mcp.config import config
from mpt_mcp.server_context import log, normalize_endpoint_url
from mpt_mcp.token_validator import normalize_token, parse_token_id, validate_token

MISSING_TOKEN_ERROR = "Missing X-MPT-Authorization header. Please provide your API token in the X-MPT-Authorization header."
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
            raise ValueError(MISSING_TOKEN_ERROR)

        await self._validate_token()

        return APIClient(base_url=self.endpoint, token=self.token)

    async def _validate_token(self) -> None:
        is_valid, token_info, error = await validate_token(self.token, self.endpoint, use_cache=not self.validate_fresh)
        if not is_valid:
            log(f"❌ Token validation failed: {error}")
            raise ValueError(f"Token validation failed: {error}. Please ensure your API token is valid and active.")

        account = (token_info or {}).get("account", {})
        log(f"✅ Token validated for {self.endpoint} - Account: {account.get('name', 'Unknown')} ({account.get('id', 'Unknown')})")


async def get_call_context(request: Request = CurrentRequest()) -> CallContext:
    """
    Build the call context from the X-MPT-* headers of the current HTTP request.

    Args:
        request: Current HTTP request, injected by FastMCP

    Returns:
        Call context with the caller's endpoint, token and validation preference
    """
    raw_token = request.headers.get("x-mpt-authorization")
    endpoint = request.headers.get("x-mpt-endpoint") or config.sse_default_base_url
    validate_fresh = request.headers.get("x-mpt-validate-fresh", "").strip().lower() in TRUTHY_HEADER_VALUES
    return CallContext(
        endpoint=normalize_endpoint_url(endpoint),
        token=normalize_token(raw_token) if raw_token else None,
        validate_fresh=validate_fresh,
    )
