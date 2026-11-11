from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.tools import ToolResult
from starlette.datastructures import Headers
from starlette.requests import Request

from mpt_mcp.analytics.events import (
    AnalyticsContext,
    PromptGetEvent,
    ResourceReadEvent,
    ToolCallEvent,
)
from mpt_mcp.analytics.logger import ANALYTICS_KEY, AnalyticsLogger, current_analytics_context
from mpt_mcp.analytics.middleware import AnalyticsMiddleware

RESPONSE_TIME_MS = 250


@pytest.fixture
def analytics():
    return AsyncMock(spec=AnalyticsLogger, enabled=True)


@pytest.fixture
def context_factory(analytics):
    def factory(**message_fields):
        context = Mock(message=Mock(**message_fields))
        context.fastmcp_context.lifespan_context = {ANALYTICS_KEY: analytics}
        return context

    return factory


@pytest.fixture
def request_factory():
    def factory(headers, query_string=b""):
        raw_headers = Headers(headers).raw
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "query_string": query_string,
            "headers": raw_headers,
            "client": ("10.0.0.1", 12345),
        }
        return Request(scope)

    return factory


@pytest.fixture
def middleware():
    return AnalyticsMiddleware(clock=Mock(side_effect=[100.0, 100.25]))


@pytest.fixture
def prompt_context(context_factory):
    context = context_factory()
    context.message.name = "recent_orders"
    return context


@pytest.fixture
def resource_context(context_factory):
    return context_factory(uri="api://openapi.json")


@pytest.fixture
def tool_context(context_factory):
    context = context_factory(arguments={})
    context.message.name = "marketplace_query"
    return context


async def test_on_call_tool_logs_success(middleware, analytics, tool_context):
    call_next = AsyncMock(return_value=ToolResult(structured_content={"data": []}))

    await middleware.on_call_tool(tool_context, call_next)  # act

    analytics.record.assert_awaited_once_with(
        ToolCallEvent(tool_name="marketplace_query", response_time_ms=RESPONSE_TIME_MS)
    )


async def test_on_call_tool_ignores_error_field(middleware, analytics, tool_context):
    call_next = AsyncMock(
        return_value=ToolResult(structured_content={"id": "ORD-1234", "error": {"id": "ERR"}})
    )

    await middleware.on_call_tool(tool_context, call_next)  # act

    analytics.record.assert_awaited_once_with(
        ToolCallEvent(tool_name="marketplace_query", response_time_ms=RESPONSE_TIME_MS)
    )


async def test_on_call_tool_logs_tool_error(middleware, analytics, tool_context):
    call_next = AsyncMock(side_effect=ToolError("Missing X-MPT-Authorization header"))

    with pytest.raises(ToolError):
        await middleware.on_call_tool(tool_context, call_next)

    analytics.record.assert_awaited_once_with(
        ToolCallEvent(
            tool_name="marketplace_query",
            response_time_ms=RESPONSE_TIME_MS,
            error_type="tool_error",
            error_message="Missing X-MPT-Authorization header",
        )
    )


async def test_on_call_tool_logs_and_reraises_exception(middleware, analytics, tool_context):
    call_next = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.on_call_tool(tool_context, call_next)

    analytics.record.assert_awaited_once_with(
        ToolCallEvent(
            tool_name="marketplace_query",
            response_time_ms=RESPONSE_TIME_MS,
            error_type="exception",
            error_message="boom",
        )
    )


async def test_on_call_tool_skips_logging_when_disabled(middleware, analytics, tool_context):
    analytics.enabled = False
    call_next = AsyncMock(return_value=ToolResult(structured_content={"data": []}))

    await middleware.on_call_tool(tool_context, call_next)  # act

    analytics.record.assert_not_awaited()


async def test_on_call_tool_without_analytics(middleware, tool_context):
    tool_context.fastmcp_context.lifespan_context = {}
    call_next = AsyncMock(return_value="result")

    result = await middleware.on_call_tool(tool_context, call_next)

    assert result == "result"


async def test_on_read_resource_logs_success(middleware, analytics, resource_context):
    call_next = AsyncMock(return_value=ResourceResult([ResourceContent(content="# Page")]))

    await middleware.on_read_resource(resource_context, call_next)  # act

    analytics.record.assert_awaited_once_with(
        ResourceReadEvent(resource_uri="api://openapi.json", response_time_ms=RESPONSE_TIME_MS)
    )


async def test_on_read_resource_reraises_exception(middleware, analytics, resource_context):
    call_next = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.on_read_resource(resource_context, call_next)

    analytics.record.assert_awaited_once_with(
        ResourceReadEvent(
            resource_uri="api://openapi.json",
            response_time_ms=RESPONSE_TIME_MS,
            error_type="resource_not_found",
            error_message="boom",
        )
    )


async def test_on_get_prompt_logs_success(middleware, analytics, prompt_context):
    call_next = AsyncMock(return_value=Mock())

    await middleware.on_get_prompt(prompt_context, call_next)  # act

    analytics.record.assert_awaited_once_with(
        PromptGetEvent(tool_name="recent_orders", response_time_ms=RESPONSE_TIME_MS)
    )


async def test_on_get_prompt_reraises_exception(middleware, analytics, prompt_context):
    call_next = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.on_get_prompt(prompt_context, call_next)

    analytics.record.assert_awaited_once_with(
        PromptGetEvent(
            tool_name="recent_orders",
            response_time_ms=RESPONSE_TIME_MS,
            error_type="prompt_error",
            error_message="boom",
        )
    )


@pytest.mark.parametrize(
    ("headers", "expected_client"),
    [
        (
            {"User-Agent": "Cursor/1.0", "X-Forwarded-For": "203.0.113.7, 10.0.0.2"},
            {"client_info": "Cursor", "client_ip": "203.0.113.7"},
        ),
        (
            {"User-Agent": "Claude-User/2.0", "X-Real-IP": "198.51.100.4"},
            {"client_info": "Claude Desktop", "client_ip": "198.51.100.4"},
        ),
        (
            {"User-Agent": "python-httpx/0.28"},
            {"client_info": "python-httpx", "client_ip": "10.0.0.1"},
        ),
        ({}, {"client_info": None, "client_ip": "10.0.0.1"}),
    ],
)
async def test_on_request_sets_analytics_context(
    middleware, context_factory, request_factory, headers, expected_client
):
    request = request_factory(
        {
            "X-MPT-Authorization": "idt:TKN-1234-5678:SECRET",
            "X-MPT-Endpoint": "https://api.s1.show/public",
            **headers,
        },
        query_string=b"session_id=abcdef123456",
    )
    call_next = AsyncMock(side_effect=lambda _: current_analytics_context.get())

    with patch("mpt_mcp.analytics.middleware.get_http_request", return_value=request):
        result = await middleware.on_request(context_factory(), call_next)

    assert result == AnalyticsContext(
        token_id="TKN-1234-5678",
        api_endpoint="https://api.s1.show",
        **expected_client,
        session_id="abcdef123456",
    )
    assert current_analytics_context.get() == AnalyticsContext()


async def test_on_request_without_http_request(middleware, context_factory):
    call_next = AsyncMock(return_value="result")

    with patch(
        "mpt_mcp.analytics.middleware.get_http_request",
        side_effect=RuntimeError("No active HTTP request found."),
    ):
        result = await middleware.on_request(context_factory(), call_next)

    assert result == "result"
