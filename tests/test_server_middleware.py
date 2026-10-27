from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request

from mpt_mcp.server_context import current_session_id, current_user_id
from mpt_mcp.server_middleware import RequestContextMiddleware


@pytest.fixture
def make_request():
    def _make_request(headers, query_string=b""):
        raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
        scope = {"type": "http", "method": "POST", "path": "/mcp", "query_string": query_string, "headers": raw_headers, "client": ("10.0.0.1", 12345)}
        return Request(scope)

    return _make_request


@pytest.fixture
def capture_log_context():
    async def _capture_log_context(context):
        return (current_user_id.get(), current_session_id.get())

    return _capture_log_context


async def test_on_request_sets_log_context_during_call(make_request, capture_log_context):
    request = make_request({"X-MPT-Authorization": "idt:TKN-1234-5678:SECRET"}, query_string=b"session_id=abcdef123456")

    with patch("mpt_mcp.server_middleware.get_http_request", return_value=request):
        result = await RequestContextMiddleware().on_request(Mock(), capture_log_context)

    assert result == ("TKN-1234-5678", "abcdef123456")


async def test_on_request_resets_log_context_after_call(make_request, capture_log_context):
    request = make_request({"X-MPT-Authorization": "idt:TKN-1234-5678:SECRET"}, query_string=b"session_id=abcdef123456")

    with patch("mpt_mcp.server_middleware.get_http_request", return_value=request):
        await RequestContextMiddleware().on_request(Mock(), capture_log_context)  # act

    assert (current_user_id.get(), current_session_id.get()) == (None, None)


async def test_on_request_without_http_request_passes_through():
    call_next = AsyncMock(return_value="result")

    with patch("mpt_mcp.server_middleware.get_http_request", side_effect=RuntimeError("No active HTTP request found.")):
        result = await RequestContextMiddleware().on_request(Mock(), call_next)

    assert result == "result"


@pytest.mark.parametrize(
    ("headers", "client_info", "client_ip"),
    [
        ({"User-Agent": "Cursor/1.0", "X-Forwarded-For": "203.0.113.7, 10.0.0.2"}, "Cursor", "203.0.113.7"),
        ({"User-Agent": "Claude-User/2.0", "X-Real-IP": "198.51.100.4"}, "Claude Desktop", "198.51.100.4"),
        ({"User-Agent": "python-httpx/0.28"}, "python-httpx", "10.0.0.1"),
        ({}, None, "10.0.0.1"),
    ],
)
async def test_on_request_sets_analytics_context(make_request, headers, client_info, client_ip):
    request = make_request({"X-MPT-Authorization": "idt:TKN-1234-5678:SECRET", "X-MPT-Endpoint": "https://api.s1.show/public", **headers})
    analytics = Mock()

    with (
        patch("mpt_mcp.server_middleware.get_http_request", return_value=request),
        patch("mpt_mcp.server_middleware.get_analytics_logger", return_value=analytics),
        patch("mpt_mcp.server_middleware.config.analytics_enabled", new=True),
    ):
        await RequestContextMiddleware().on_request(Mock(), AsyncMock())  # act

    analytics.set_context.assert_called_once_with(token="idt:TKN-1234-5678:SECRET", endpoint="https://api.s1.show", client_info=client_info, client_ip=client_ip)
