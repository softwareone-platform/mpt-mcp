import contextlib
import sys
from contextvars import ContextVar

# Ensure stderr is unbuffered so startup and request logs appear in Docker/console immediately
if hasattr(sys.stderr, "reconfigure"):
    with contextlib.suppress(Exception):
        sys.stderr.reconfigure(line_buffering=True)

from .api_client import APIClient
from .config import config

_current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)
_current_endpoint: ContextVar[str | None] = ContextVar("current_endpoint", default=None)
_current_validate_fresh: ContextVar[bool] = ContextVar("current_validate_fresh", default=False)


def log(message: str, **kwargs):
    session_id = _current_session_id.get()
    user_id = _current_user_id.get()
    context_parts = []
    if session_id:
        context_parts.append(f"sess:{session_id[:8]}")
    if user_id:
        context_parts.append(f"user:{user_id}")
    prefix = f"[{('|'.join(context_parts))}] " if context_parts else ""
    print(f"{prefix}{message}", file=sys.stderr, flush=True, **kwargs)


def normalize_endpoint_url(endpoint: str) -> str:
    if not endpoint:
        return endpoint
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/public"):
        endpoint = endpoint[:-7]
    return endpoint


def get_current_credentials() -> tuple[str | None, str]:
    token = _current_token.get()
    endpoint = _current_endpoint.get() or config.sse_default_base_url
    return token, normalize_endpoint_url(endpoint)


async def get_client_api_client_http(validate_token: bool = True) -> APIClient:
    token, endpoint = get_current_credentials()
    if not token:
        raise ValueError("Missing X-MPT-Authorization header. Please provide your API token in the X-MPT-Authorization header.")
    if validate_token:
        from .token_validator import validate_token

        use_cache = not _current_validate_fresh.get()
        is_valid, token_info, error = await validate_token(token, endpoint, use_cache=use_cache)
        if not is_valid:
            log(f"❌ Token validation failed: {error}")
            raise ValueError(f"Token validation failed: {error}. Please ensure your API token is valid and active.")
        if token_info:
            account_name = token_info.get("account", {}).get("name", "Unknown")
            account_id = token_info.get("account", {}).get("id", "Unknown")
            log(f"✅ Token validated for {endpoint} - Account: {account_name} ({account_id})")
        else:
            log(f"✅ Token validated for {endpoint}")
    return APIClient(base_url=endpoint, token=token)
