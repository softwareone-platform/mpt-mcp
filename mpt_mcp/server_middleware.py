from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from mpt_mcp.analytics import get_analytics_logger
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.config import config
from mpt_mcp.server_context import current_session_id, current_user_id, log

if TYPE_CHECKING:
    from starlette.requests import Request


class RequestContextMiddleware(Middleware):
    """Tag logs and analytics events of each MCP request with the caller's identity."""

    activity_log_cooldown = timedelta(seconds=30)

    def __init__(self) -> None:
        self._last_activity_log: dict[str, datetime] = {}

    async def on_request(self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]) -> Any:
        """Bind the caller's user and session ID to logs and analytics for the duration of the request."""
        try:
            request = get_http_request()
        except RuntimeError:
            return await call_next(context)

        call_context = await get_call_context(request)
        analytics = get_analytics_logger()
        if analytics and config.analytics_enabled:
            analytics.set_context(
                token=call_context.token or "",
                endpoint=call_context.endpoint,
                client_info=self._client_info(request),
                client_ip=self._client_ip(request),
            )

        user_token = current_user_id.set(call_context.user_id)
        session_token = current_session_id.set(request.query_params.get("session_id"))
        try:
            self._log_activity(call_context)
            return await call_next(context)
        finally:
            current_user_id.reset(user_token)
            current_session_id.reset(session_token)

    @staticmethod
    def _client_info(request: Request) -> str | None:
        user_agent = request.headers.get("user-agent", "")
        if "cursor" in user_agent.lower():
            return "Cursor"

        if "claude" in user_agent.lower():
            return "Claude Desktop"

        if user_agent:
            return user_agent.split("/")[0][:50]

        return None

    @staticmethod
    def _client_ip(request: Request) -> str | None:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        client_ip = request.headers.get("x-real-ip")
        if not client_ip and request.client:
            client_ip = request.client.host

        return client_ip

    def _log_activity(self, call_context: CallContext) -> None:
        caller = call_context.user_id or "anonymous"
        log_key = f"{caller}@{call_context.endpoint}"
        now = datetime.now()
        if now - self._last_activity_log.get(log_key, datetime.min) < self.activity_log_cooldown:
            return

        endpoint_display = call_context.endpoint
        if endpoint_display.startswith("https://"):
            endpoint_display = endpoint_display.removeprefix("https://").split("/")[0]
        token_status = "✓" if call_context.token else "✗"
        log(f"📨 {caller} @ {endpoint_display} [{token_status}] (active)")
        self._last_activity_log[log_key] = now
