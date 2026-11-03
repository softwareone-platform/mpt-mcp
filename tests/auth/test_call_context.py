import re
from unittest.mock import AsyncMock, patch

import pytest
from starlette.datastructures import Headers
from starlette.requests import Request

from mpt_mcp.auth.call_context import (
    NO_CREDENTIALS_ERROR,
    CallContext,
    get_call_context,
    read_call_context,
)
from mpt_mcp.config import config
from mpt_mcp.marketplace.api_client import APIClient


@pytest.fixture
def request_factory():
    def factory(headers):
        raw_headers = Headers(headers).raw
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "query_string": b"",
            "headers": raw_headers,
        })

    return factory


def test_read_call_context_reads_mpt_headers(request_factory):
    request = request_factory({
        "X-MPT-Authorization": "Bearer idt:TKN-1234-5678:SECRET",
        "X-MPT-Endpoint": "https://api.s1.show/public/",
        "X-MPT-Validate-Fresh": "true",
    })

    result = read_call_context(request)

    assert result == CallContext(
        endpoint="https://api.s1.show", token="idt:TKN-1234-5678:SECRET", validate_fresh=True
    )


def test_call_context_defaults_without_headers(request_factory):
    request = request_factory({})

    result = read_call_context(request)

    assert result == CallContext(
        endpoint=config.http_default_base_url, token=None, validate_fresh=False
    )


def test_get_call_context_reads_http_request(request_factory, monkeypatch):
    request = request_factory({"X-MPT-Authorization": "idt:TKN-1234-5678:SECRET"})
    monkeypatch.setattr("mpt_mcp.auth.call_context.get_http_request", lambda: request)

    result = get_call_context()

    assert result == read_call_context(request)


def test_get_call_context_reads_environment(monkeypatch):
    monkeypatch.setattr(config, "marketplace_api_base_url", "https://api.test.com/public/")
    monkeypatch.setattr(config, "marketplace_api_token", "Bearer idt:TKN-1234-5678:SECRET")

    result = get_call_context()

    assert result == CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [
        ("1", True),
        ("YES", True),
        (" true ", True),
        ("false", False),
        ("", False),
    ],
)
def test_read_call_context_validate_fresh_values(request_factory, header_value, expected):
    request = request_factory({"X-MPT-Validate-Fresh": header_value})

    result = read_call_context(request)

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

    with pytest.raises(ValueError, match=re.escape(NO_CREDENTIALS_ERROR)):
        await call_context.create_api_client()


async def test_create_api_client_invalid_token():
    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")

    with (
        patch(
            "mpt_mcp.auth.call_context.validate_token",
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
        "mpt_mcp.auth.call_context.validate_token",
        new_callable=AsyncMock,
        return_value=(True, {"account": {"name": "Test", "id": "ACC-1"}}, None),
    ) as mock_validate:
        await call_context.create_api_client()  # act

    mock_validate.assert_awaited_once_with(
        "idt:TKN-1234-5678:SECRET", "https://api.test.com", use_cache=use_cache
    )


async def test_create_api_client_for_caller_endpoint():
    call_context = CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")

    with patch(
        "mpt_mcp.auth.call_context.validate_token",
        new_callable=AsyncMock,
        return_value=(True, None, None),
    ):
        result = await call_context.create_api_client()

    assert isinstance(result, APIClient)
    assert (result.base_url, result.token) == (
        "https://api.test.com",
        "Bearer idt:TKN-1234-5678:SECRET",
    )


async def test_missing_authorization_header():
    with pytest.raises(ValueError) as exc_info:
        await CallContext(endpoint="https://api.test.com", token=None).create_api_client()

    error_message = str(exc_info.value)
    assert "Missing X-MPT-Authorization header" in error_message or "Missing" in error_message


async def test_missing_auth_error_message_is_clear():
    with pytest.raises(ValueError) as exc_info:
        await CallContext(endpoint="https://api.test.com", token=None).create_api_client()

    error_message = str(exc_info.value)
    assert "Missing" in error_message
    assert "X-MPT-Authorization" in error_message
    assert "header" in error_message.lower()
