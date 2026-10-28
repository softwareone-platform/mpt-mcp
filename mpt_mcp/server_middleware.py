import logging
from datetime import datetime, timedelta
from typing import Any

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.log_config import current_session_id, current_user_id

logger = logging.getLogger(__name__)


class RequestContextMiddleware(Middleware):
    """Tag the logs of each MCP request with the caller's user and session ID."""

    activity_log_cooldown = timedelta(seconds=30)

    def __init__(self) -> None:
        self._last_activity_log: dict[str, datetime] = {}

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        """Bind the caller's user and session ID to the logs for the duration of the request."""
        try:
            request = get_http_request()
        except RuntimeError:
            return await call_next(context)

        call_context = await get_call_context(request)
        user_token = current_user_id.set(call_context.user_id)
        session_token = current_session_id.set(request.query_params.get("session_id"))
        try:
            self._log_activity(call_context)
            return await call_next(context)
        finally:
            current_user_id.reset(user_token)
            current_session_id.reset(session_token)

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
        logger.info(f"📨 {caller} @ {endpoint_display} [{token_status}] (active)")
        self._last_activity_log[log_key] = now
