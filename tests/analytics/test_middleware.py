import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.tools import ToolResult
from starlette.requests import Request

from mpt_mcp.analytics.middleware import AnalyticsMiddleware


@pytest.fixture
def analytics():
    with patch("mpt_mcp.analytics.middleware.get_analytics_logger") as get_analytics_logger:
        analytics_logger = AsyncMock(enabled=True)
        analytics_logger.set_context = Mock()
        get_analytics_logger.return_value = analytics_logger
        yield analytics_logger


@pytest.fixture
def make_request():
    def _make_request(headers, query_string=b""):
        raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "query_string": query_string,
            "headers": raw_headers,
            "client": ("10.0.0.1", 12345),
        }
        return Request(scope)

    return _make_request


@pytest.fixture
def middleware():
    # Every call takes 250 ms: the clock is read at the start and at the end of the call
    return AnalyticsMiddleware(clock=Mock(side_effect=[100.0, 100.25]))


@pytest.fixture
def resource_context():
    return Mock(message=Mock(uri="api://openapi.json"))


@pytest.fixture
def tool_context():
    context = Mock(message=Mock(arguments={}))
    context.message.name = "marketplace_query"
    return context


async def test_on_call_tool_logs_success(middleware, analytics, tool_context):
    call_next = AsyncMock(return_value=ToolResult(structured_content={"data": []}))

    await middleware.on_call_tool(tool_context, call_next)  # act

    analytics.log_tool_call.assert_awaited_once_with(
        tool_name="marketplace_query", response_time_ms=250, success=True, error_message=None
    )


async def test_on_call_tool_logs_error_payload(middleware, analytics, tool_context):
    call_next = AsyncMock(
        return_value=ToolResult(structured_content={"error": "Missing X-MPT-Authorization header"})
    )

    await middleware.on_call_tool(tool_context, call_next)  # act

    analytics.log_tool_call.assert_awaited_once_with(
        tool_name="marketplace_query",
        response_time_ms=250,
        success=False,
        error_message="Missing X-MPT-Authorization header",
    )


async def test_on_call_tool_logs_and_reraises_exception(middleware, analytics, tool_context):
    call_next = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.on_call_tool(tool_context, call_next)

    analytics.log_tool_call.assert_awaited_once_with(
        tool_name="marketplace_query",
        response_time_ms=250,
        success=False,
        error_type="exception",
        error_message="boom",
    )


async def test_on_call_tool_skips_logging_when_disabled(middleware, analytics, tool_context):
    analytics.enabled = False
    call_next = AsyncMock(return_value=ToolResult(structured_content={"data": []}))

    await middleware.on_call_tool(tool_context, call_next)  # act

    analytics.log_tool_call.assert_not_awaited()


@pytest.mark.parametrize(
    ("content", "success", "error_message"),
    [
        (json.dumps({"spec": {}}), True, None),
        (json.dumps({"error": "Authentication required"}), False, "Authentication required"),
        ("# Markdown page", True, None),
        ("{not json", True, None),
    ],
)
async def test_on_read_resource_logs_outcome(
    middleware, analytics, resource_context, content, success, error_message
):
    call_next = AsyncMock(return_value=ResourceResult([ResourceContent(content=content)]))

    await middleware.on_read_resource(resource_context, call_next)  # act

    analytics.log_resource_read.assert_awaited_once_with(
        resource_uri="api://openapi.json",
        response_time_ms=250,
        success=success,
        error_message=error_message,
    )


async def test_on_read_resource_logs_and_reraises_exception(
    middleware, analytics, resource_context
):
    call_next = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.on_read_resource(resource_context, call_next)

    analytics.log_resource_read.assert_awaited_once_with(
        resource_uri="api://openapi.json", response_time_ms=250, success=False, error_message="boom"
    )


@pytest.mark.parametrize(
    ("headers", "client_info", "client_ip"),
    [
        (
            {"User-Agent": "Cursor/1.0", "X-Forwarded-For": "203.0.113.7, 10.0.0.2"},
            "Cursor",
            "203.0.113.7",
        ),
        (
            {"User-Agent": "Claude-User/2.0", "X-Real-IP": "198.51.100.4"},
            "Claude Desktop",
            "198.51.100.4",
        ),
        ({"User-Agent": "python-httpx/0.28"}, "python-httpx", "10.0.0.1"),
        ({}, None, "10.0.0.1"),
    ],
)
async def test_on_request_sets_analytics_context(
    middleware, analytics, make_request, headers, client_info, client_ip
):
    request = make_request(
        {
            "X-MPT-Authorization": "idt:TKN-1234-5678:SECRET",
            "X-MPT-Endpoint": "https://api.s1.show/public",
            **headers,
        },
        query_string=b"session_id=abcdef123456",
    )

    with patch("mpt_mcp.analytics.middleware.get_http_request", return_value=request):
        await middleware.on_request(Mock(), AsyncMock())  # act

    analytics.set_context.assert_called_once_with(
        token="idt:TKN-1234-5678:SECRET",
        endpoint="https://api.s1.show",
        client_info=client_info,
        client_ip=client_ip,
        session_id="abcdef123456",
    )


async def test_on_request_without_http_request_passes_through(middleware, analytics):
    call_next = AsyncMock(return_value="result")

    with patch(
        "mpt_mcp.analytics.middleware.get_http_request",
        side_effect=RuntimeError("No active HTTP request found."),
    ):
        result = await middleware.on_request(Mock(), call_next)

    assert result == "result"
