import json
import time
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from mpt_mcp.analytics.logger import get_analytics_logger
from mpt_mcp.call_context import read_call_context

CLIENT_NAME_MAX_LENGTH = 50

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp.resources import ResourceResult
    from fastmcp.tools import ToolResult
    from mcp_types import CallToolRequestParams, ReadResourceRequestParams
    from starlette.requests import Request


class AnalyticsMiddleware(Middleware):
    """Record a usage event for every tool call and resource read."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """
        Initialize the middleware.

        Args:
            clock: Monotonic clock in seconds used to measure response times
        """
        self._clock = clock

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Record the tool call with its response time and outcome."""
        analytics = get_analytics_logger()
        if not analytics or not analytics.enabled:
            return await call_next(context)

        start_time = self._clock()
        try:
            result = await call_next(context)
        except Exception as error:
            await analytics.log_tool_call(
                tool_name=context.message.name,
                response_time_ms=self._elapsed_ms(start_time),
                success=False,
                error_type="tool_error" if isinstance(error, ToolError) else "exception",
                error_message=str(error),
            )
            raise

        await analytics.log_tool_call(
            tool_name=context.message.name,
            response_time_ms=self._elapsed_ms(start_time),
            success=not result.is_error,
            error_message="Tool returned an error result" if result.is_error else None,
        )

        return result

    async def on_read_resource(
        self,
        context: MiddlewareContext[ReadResourceRequestParams],
        call_next: CallNext[ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Record the resource read with its response time and outcome."""
        analytics = get_analytics_logger()
        if not analytics or not analytics.enabled:
            return await call_next(context)

        start_time = self._clock()
        try:
            result = await call_next(context)
        except Exception as error:
            await analytics.log_resource_read(
                resource_uri=str(context.message.uri),
                response_time_ms=self._elapsed_ms(start_time),
                success=False,
                error_message=str(error),
            )
            raise

        error_message = self._resource_error(result)
        await analytics.log_resource_read(
            resource_uri=str(context.message.uri),
            response_time_ms=self._elapsed_ms(start_time),
            success=error_message is None,
            error_message=error_message,
        )

        return result

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        """Bind the caller's token, endpoint and client to the analytics events of the request."""
        analytics = get_analytics_logger()
        if not analytics or not analytics.enabled:
            return await call_next(context)

        try:
            request = get_http_request()
        except RuntimeError:
            return await call_next(context)

        call_context = read_call_context(request)
        analytics.set_context(
            token=call_context.token or "",
            endpoint=call_context.endpoint,
            client_info=self._client_info(request),
            client_ip=self._client_ip(request),
            session_id=request.query_params.get("session_id"),
        )

        return await call_next(context)

    @staticmethod
    def _client_info(request: Request) -> str | None:
        user_agent = request.headers.get("user-agent", "")
        if "cursor" in user_agent.lower():
            return "Cursor"

        if "claude" in user_agent.lower():
            return "Claude Desktop"

        if user_agent:
            return user_agent.split("/")[0][:CLIENT_NAME_MAX_LENGTH]

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

    def _elapsed_ms(self, start_time: float) -> int:
        return int((self._clock() - start_time) * 1000)

    @staticmethod
    def _resource_error(result: ResourceResult) -> str | None:
        # Resources report failures as a JSON object with an "error" key
        first_content = result.contents[0].content if result.contents else None
        if not isinstance(first_content, str) or not first_content.lstrip().startswith("{"):
            return None

        try:
            payload = json.loads(first_content)
        except json.JSONDecodeError:
            return None

        return payload.get("error") if isinstance(payload, dict) else None
