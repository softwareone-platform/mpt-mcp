from collections import defaultdict
from datetime import datetime, timedelta

from starlette.requests import Request

from .analytics import get_analytics_logger
from .api_client import APIClient
from .config import config
from .server_context import (
    _current_endpoint,
    _current_session_id,
    _current_token,
    _current_user_id,
    _current_validate_fresh,
    log,
)
from .token_validator import normalize_token

_last_log_time: dict[str, datetime] = defaultdict(lambda: datetime.min)
_log_cooldown = timedelta(seconds=30)


class CredentialsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            auth_header_raw = request.headers.get("x-mpt-authorization") or request.headers.get("X-MPT-Authorization")
            auth_header = normalize_token(auth_header_raw) if auth_header_raw else auth_header_raw
            endpoint_header = request.headers.get("x-mpt-endpoint") or request.headers.get("X-MPT-Endpoint")
            validate_fresh = (request.headers.get("x-mpt-validate-fresh") or request.headers.get("X-MPT-Validate-Fresh") or "").strip().lower() in ("1", "true", "yes")

            user_id = None
            if auth_header:
                user_id = APIClient._extract_user_id(auth_header)
            session_id = request.query_params.get("session_id")

            user_agent = request.headers.get("user-agent", "")
            client_info = None
            if "cursor" in user_agent.lower():
                client_info = "Cursor"
            elif "claude" in user_agent.lower():
                client_info = "Claude Desktop"
            elif user_agent:
                client_info = user_agent.split("/")[0][:50]

            client_ip = None
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
            else:
                client_ip = request.headers.get("x-real-ip")
                if not client_ip and request.client:
                    client_ip = request.client.host

            token_ctx = user_ctx = session_ctx = endpoint_ctx = None
            if auth_header:
                token_ctx = _current_token.set(auth_header)
            if endpoint_header:
                endpoint_ctx = _current_endpoint.set(endpoint_header)
            if validate_fresh:
                _ = _current_validate_fresh.set(True)
            if user_id:
                user_ctx = _current_user_id.set(user_id)
            if session_id:
                session_ctx = _current_session_id.set(session_id)

            analytics = get_analytics_logger()
            if analytics and config.analytics_enabled:
                analytics.set_context(
                    token=auth_header or "",
                    endpoint=endpoint_header or config.sse_default_base_url,
                    client_info=client_info,
                    client_ip=client_ip,
                )

            try:
                if request.url.path == "/mcp" and request.method == "POST":
                    log_key = f"{user_id or 'anonymous'}@{endpoint_header or config.sse_default_base_url}"
                    now = datetime.now()
                    if now - _last_log_time[log_key] >= _log_cooldown:
                        endpoint_display = endpoint_header or config.sse_default_base_url
                        if endpoint_display.startswith("https://"):
                            endpoint_display = endpoint_display.replace("https://", "").split("/")[0]
                        token_status = "✓" if auth_header else "✗"
                        log(f"📨 {user_id or 'anonymous'} @ {endpoint_display} [{token_status}] (active)")
                        _last_log_time[log_key] = now
                await self.app(scope, receive, send)
            finally:
                if token_ctx is not None:
                    _current_token.reset(token_ctx)
                if endpoint_ctx is not None:
                    _current_endpoint.reset(endpoint_ctx)
                if user_ctx is not None:
                    _current_user_id.reset(user_ctx)
                if session_ctx is not None:
                    _current_session_id.reset(session_ctx)
        else:
            await self.app(scope, receive, send)
