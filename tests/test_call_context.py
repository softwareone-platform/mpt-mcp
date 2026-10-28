from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from mpt_mcp.api_client import APIClient
from mpt_mcp.call_context import (
    MISSING_TOKEN_ERROR,
    CallContext,
    get_call_context,
    normalize_endpoint_url,
)
from mpt_mcp.config import config


@pytest.fixture
def make_request():
    def _make_request(headers):
        raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "query_string": b"",
            "headers": raw_headers,
        })

    return _make_request


async def test_get_call_context_reads_mpt_headers(make_request):
    request = make_request({
        "X-MPT-Authorization": "Bearer idt:TKN-1234-5678:SECRET",
        "X-MPT-Endpoint": "https://api.s1.show/public/",
        "X-MPT-Validate-Fresh": "true",
    })

    result = await get_call_context(request)

    assert result == CallContext(
        endpoint="https://api.s1.show", token="idt:TKN-1234-5678:SECRET", validate_fresh=True
    )


async def test_get_call_context_defaults_without_headers(make_request):
    request = make_request({})

    result = await get_call_context(request)

    assert result == CallContext(
        endpoint=config.sse_default_base_url, token=None, validate_fresh=False
    )


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [("1", True), ("YES", True), (" true ", True), ("false", False), ("", False)],
)
async def test_get_call_context_validate_fresh_values(make_request, header_value, expected):
    request = make_request({"X-MPT-Validate-Fresh": header_value})

    result = await get_call_context(request)

    assert result.validate_fresh is expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [("idt:TKN-1234-5678:SECRET", "TKN-1234-5678"), (None, None)],
)
def test_user_id_from_token(token, expected):
    call_context = CallContext(endpoint="https://api.test.com", token=token)

    result = call_context.user_id

    assert result == expected


async def test_create_api_client_without_token_raises():
    call_context = CallContext(endpoint="https://api.test.com", token=None)

    with pytest.raises(ValueError, match=MISSING_TOKEN_ERROR):
        await call_context.create_api_client()


async def test_create_api_client_with_invalid_token_raises():
    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")

    with (
        patch(
            "mpt_mcp.call_context.validate_token",
            new_callable=AsyncMock,
            return_value=(False, None, "Token expired"),
        ),
        pytest.raises(ValueError, match="Token validation failed: Token expired"),
    ):
        await call_context.create_api_client()


@pytest.mark.parametrize(
    ("validate_fresh", "use_cache"),
    [(False, True), (True, False)],
)
async def test_create_api_client_validates_token(validate_fresh, use_cache):
    call_context = CallContext(
        endpoint="https://api.test.com",
        token="idt:TKN-1234-5678:SECRET",
        validate_fresh=validate_fresh,
    )

    with patch(
        "mpt_mcp.call_context.validate_token",
        new_callable=AsyncMock,
        return_value=(True, {"account": {"name": "Test", "id": "ACC-1"}}, None),
    ) as mock_validate:
        await call_context.create_api_client()  # act

    mock_validate.assert_awaited_once_with(
        "idt:TKN-1234-5678:SECRET", "https://api.test.com", use_cache=use_cache
    )


async def test_create_api_client_returns_client_for_caller_endpoint():
    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")

    with patch(
        "mpt_mcp.call_context.validate_token",
        new_callable=AsyncMock,
        return_value=(True, None, None),
    ):
        result = await call_context.create_api_client()

    assert isinstance(result, APIClient)
    assert (result.base_url, result.token) == (
        "https://api.test.com",
        "Bearer idt:TKN-1234-5678:SECRET",
    )


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://api.s1.show/public", "https://api.s1.show"),
        ("https://api.platform.softwareone.com/public", "https://api.platform.softwareone.com"),
        ("https://api.s1.show/public/", "https://api.s1.show"),
        ("https://api.s1.show", "https://api.s1.show"),
        ("https://api.s1.show/", "https://api.s1.show"),
        ("https://api.s1.show//", "https://api.s1.show"),
        ("http://localhost:8080/public", "http://localhost:8080"),
        ("https://api.example.com/api/v1", "https://api.example.com/api/v1"),
        ("https://api.example.com/Public", "https://api.example.com/Public"),
        ("/public", ""),
        ("", ""),
    ],
)
def test_normalize_endpoint_url(endpoint, expected):
    result = normalize_endpoint_url(endpoint)

    assert result == expected


@pytest.mark.asyncio
async def test_missing_authorization_header():
    from mpt_mcp.call_context import CallContext

    with pytest.raises(ValueError) as exc_info:
        await CallContext(endpoint="https://api.test.com", token=None).create_api_client()

    error_message = str(exc_info.value)
    assert "Missing X-MPT-Authorization header" in error_message or "Missing" in error_message


@pytest.mark.asyncio
async def test_missing_auth_error_message_is_clear():
    from mpt_mcp.call_context import CallContext

    with pytest.raises(ValueError) as exc_info:
        await CallContext(endpoint="https://api.test.com", token=None).create_api_client()

    error_message = str(exc_info.value)

    # Should contain key information
    assert "Missing" in error_message
    assert "X-MPT-Authorization" in error_message
    assert "header" in error_message.lower()
