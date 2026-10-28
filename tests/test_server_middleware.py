from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request

from mpt_mcp.log_config import current_session_id, current_user_id
from mpt_mcp.server_middleware import RequestContextMiddleware


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
def capture_log_context():
    async def _capture_log_context(context):
        return (current_user_id.get(), current_session_id.get())

    return _capture_log_context


async def test_on_request_sets_log_context_during_call(make_request, capture_log_context):
    request = make_request(
        {"X-MPT-Authorization": "idt:TKN-1234-5678:SECRET"}, query_string=b"session_id=abcdef123456"
    )

    with patch("mpt_mcp.server_middleware.get_http_request", return_value=request):
        result = await RequestContextMiddleware().on_request(Mock(), capture_log_context)

    assert result == ("TKN-1234-5678", "abcdef123456")


async def test_on_request_resets_log_context_after_call(make_request, capture_log_context):
    request = make_request(
        {"X-MPT-Authorization": "idt:TKN-1234-5678:SECRET"}, query_string=b"session_id=abcdef123456"
    )

    with patch("mpt_mcp.server_middleware.get_http_request", return_value=request):
        await RequestContextMiddleware().on_request(Mock(), capture_log_context)  # act

    assert (current_user_id.get(), current_session_id.get()) == (None, None)


async def test_on_request_without_http_request_passes_through():
    call_next = AsyncMock(return_value="result")

    with patch(
        "mpt_mcp.server_middleware.get_http_request",
        side_effect=RuntimeError("No active HTTP request found."),
    ):
        result = await RequestContextMiddleware().on_request(Mock(), call_next)

    assert result == "result"
