import time
from typing import TYPE_CHECKING, Any, override

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from mpt_mcp.analytics.events import (
    AnalyticsContext,
    PromptGetEvent,
    ResourceReadEvent,
    ToolCallEvent,
)
from mpt_mcp.analytics.logger import ANALYTICS_KEY, AnalyticsLogger, current_analytics_context
from mpt_mcp.auth.call_context import read_call_context

CLIENT_NAME_MAX_LENGTH = 50

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp.prompts import PromptResult
    from fastmcp.resources import ResourceResult
    from fastmcp.tools import ToolResult
    from mcp_types import (
        CallToolRequestParams,
        GetPromptRequestParams,
        ReadResourceRequestParams,
    )
    from starlette.requests import Request


class AnalyticsMiddleware(Middleware):  # noqa: WPS214
    """Record a usage event for every tool call, prompt get and resource read."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """
        Initialize the middleware.

        Args:
            clock: Monotonic clock in seconds used to measure response times
        """
        self._clock = clock

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Record the tool call with its response time and outcome."""
        analytics = self._analytics(context)
        if analytics is None:
            # Every middleware hook passes the request on with call_next(context)
            return await call_next(context)  # noqa: WPS204

        tool_name = context.message.name
        start_time = self._clock()
        try:
            result = await call_next(context)
        except Exception as error:
            await analytics.record(
                ToolCallEvent(
                    tool_name=tool_name,
                    response_time_ms=self._elapsed_ms(start_time),
                    error_type="tool_error" if isinstance(error, ToolError) else "exception",
                    error_message=str(error),
                )
            )
            raise

        await analytics.record(
            ToolCallEvent(
                tool_name=tool_name,
                response_time_ms=self._elapsed_ms(start_time),
                error_message="Tool returned an error result" if result.is_error else None,
            )
        )
        return result

    @override
    async def on_get_prompt(
        self,
        context: MiddlewareContext[GetPromptRequestParams],
        call_next: CallNext[GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        """Record the prompt get with its response time and outcome."""
        analytics = self._analytics(context)
        if analytics is None:
            return await call_next(context)

        prompt_name = context.message.name
        start_time = self._clock()
        try:
            result = await call_next(context)
        except Exception as error:
            await analytics.record(
                PromptGetEvent(
                    tool_name=prompt_name,
                    response_time_ms=self._elapsed_ms(start_time),
                    error_type="prompt_error",
                    error_message=str(error),
                )
            )
            raise

        await analytics.record(
            PromptGetEvent(tool_name=prompt_name, response_time_ms=self._elapsed_ms(start_time))
        )
        return result

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[ReadResourceRequestParams],
        call_next: CallNext[ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Record the resource read with its response time and outcome."""
        analytics = self._analytics(context)
        if analytics is None:
            return await call_next(context)

        resource_uri = str(context.message.uri)
        start_time = self._clock()
        try:
            result = await call_next(context)
        except Exception as error:
            await analytics.record(
                ResourceReadEvent(
                    resource_uri=resource_uri,
                    response_time_ms=self._elapsed_ms(start_time),
                    error_type="resource_not_found",
                    error_message=str(error),
                )
            )
            raise

        await analytics.record(
            ResourceReadEvent(
                resource_uri=resource_uri, response_time_ms=self._elapsed_ms(start_time)
            )
        )
        return result

    @override
    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        """Bind the caller's token, endpoint and client to the analytics events of the request."""
        if self._analytics(context) is None:
            return await call_next(context)

        try:
            request = get_http_request()
        except RuntimeError:
            return await call_next(context)

        call_context = read_call_context(request)
        analytics_context = AnalyticsContext(
            token_id=call_context.user_id,
            api_endpoint=call_context.endpoint,
            client_info=self._client_info(request),
            client_ip=self._client_ip(request),
            session_id=request.query_params.get("session_id"),
        )
        context_token = current_analytics_context.set(analytics_context)
        # Resetting in finally is how contextvars restores a value set for one request
        try:  # noqa: WPS501
            return await call_next(context)
        finally:
            current_analytics_context.reset(context_token)

    def _analytics(self, context: MiddlewareContext[Any]) -> AnalyticsLogger | None:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return None

        analytics: AnalyticsLogger | None = fastmcp_context.lifespan_context.get(ANALYTICS_KEY)
        return analytics if analytics is not None and analytics.enabled else None

    def _client_info(self, request: Request) -> str | None:
        user_agent = request.headers.get("user-agent", "")
        if "cursor" in user_agent.lower():
            return "Cursor"

        if "claude" in user_agent.lower():
            return "Claude Desktop"

        if user_agent:
            return user_agent.split("/")[0][:CLIENT_NAME_MAX_LENGTH]

        return None

    def _client_ip(self, request: Request) -> str | None:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        client_ip = request.headers.get("x-real-ip")
        if not client_ip and request.client:
            client_ip = request.client.host

        return client_ip

    def _elapsed_ms(self, start_time: float) -> int:
        return int((self._clock() - start_time) * 1000)
