import contextlib
import ipaddress
import sys
from contextvars import ContextVar
from urllib.parse import urlparse

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


def validate_endpoint_url(endpoint: str) -> tuple[bool, str | None]:
    """Validate a client-supplied endpoint URL to prevent SSRF / credential exfiltration.

    Returns (is_valid, error). The endpoint must use https, must not point at a
    private/loopback/link-local/reserved/multicast IP (e.g. cloud metadata at
    169.254.169.254), and its host must fall under the configured allowlist.
    """
    parsed = urlparse(endpoint)

    if parsed.scheme != "https":
        return False, "endpoint must use https"

    hostname = parsed.hostname
    if not hostname:
        return False, "endpoint host not allowed"

    # If the hostname is a literal IP address, block internal/reserved ranges.
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None  # Not an IP literal -> treat as a DNS name and continue.
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast):
        return False, "endpoint host not allowed"

    hostname = hostname.lower()

    allowed = [h.strip().lower() for h in (config.mpt_allowed_endpoint_hosts or "").split(",") if h.strip()]
    # Always allow the trusted default base URL's host.
    default_host = urlparse(config.sse_default_base_url).hostname
    if default_host:
        allowed.append(default_host.lower())

    for suffix in allowed:
        if hostname == suffix or hostname.endswith("." + suffix):
            return True, None

    return False, "endpoint host not in allowlist"


def get_current_credentials() -> tuple[str | None, str]:
    token = _current_token.get()
    raw_endpoint = _current_endpoint.get()
    endpoint = normalize_endpoint_url(raw_endpoint or config.sse_default_base_url)
    # Only validate a client-supplied endpoint header; the default base URL is trusted.
    if raw_endpoint:
        is_valid, error = validate_endpoint_url(endpoint)
        if not is_valid:
            raise ValueError(f"Invalid X-MPT-Endpoint: {error}")
    return token, endpoint


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
