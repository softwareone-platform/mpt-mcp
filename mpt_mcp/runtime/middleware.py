import datetime as dt
import logging
from typing import Any

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from mpt_mcp.auth.call_context import CallContext, read_call_context
from mpt_mcp.runtime.logging import current_session_id, current_user_id

logger = logging.getLogger(__name__)

ACTIVITY_LOG_COOLDOWN_SECONDS = 30
NEVER_LOGGED = dt.datetime.min.replace(tzinfo=dt.UTC)


class RequestContextMiddleware(Middleware):
    """Tag the logs of each MCP request with the caller's user and session ID."""

    activity_log_cooldown = dt.timedelta(seconds=ACTIVITY_LOG_COOLDOWN_SECONDS)

    def __init__(self) -> None:
        self._last_activity_log: dict[str, dt.datetime] = {}

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        """Bind the caller's user and session ID to the logs for the duration of the request."""
        try:
            request = get_http_request()
        except RuntimeError:
            return await call_next(context)

        call_context = read_call_context(request)
        user_token = current_user_id.set(call_context.user_id)
        session_token = current_session_id.set(request.query_params.get("session_id"))
        # Resetting in finally is how contextvars restores a value set for one request
        try:  # noqa: WPS501
            self._log_activity(call_context)
            return await call_next(context)
        finally:
            current_user_id.reset(user_token)
            current_session_id.reset(session_token)

    def _log_activity(self, call_context: CallContext) -> None:
        caller = call_context.user_id or "anonymous"
        log_key = f"{caller}@{call_context.endpoint}"
        now = dt.datetime.now(dt.UTC)
        if now - self._last_activity_log.get(log_key, NEVER_LOGGED) < self.activity_log_cooldown:
            return

        endpoint_display = call_context.endpoint
        if endpoint_display.startswith("https://"):
            endpoint_display = endpoint_display.removeprefix("https://").split("/")[0]
        token_status = "token" if call_context.token else "no token"
        logger.info("%s @ %s [%s] (active)", caller, endpoint_display, token_status)
        self._last_activity_log[log_key] = now
