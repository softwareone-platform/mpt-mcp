#!/usr/bin/env python3
"""
Tests for MCP server middleware: CredentialsMiddleware (X-MPT-Authorization, X-MPT-Endpoint, X-MPT-Validate-Fresh).
"""

import pytest

from src.server_context import _current_endpoint, _current_token, _current_validate_fresh
from src.server_middleware import CredentialsMiddleware


async def _capture_context_app(scope, receive, send):
    """Minimal ASGI app that captures credential context and returns it in a body."""
    token = _current_token.get()
    endpoint = _current_endpoint.get()
    validate_fresh = _current_validate_fresh.get()
    body = f"token={repr(token)}|endpoint={repr(endpoint)}|validate_fresh={validate_fresh}".encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _make_scope(path: str = "/mcp", method: str = "POST", headers: list | None = None):
    scope = {
        "type": "http",
        "path": path,
        "method": method,
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 8080),
        "scheme": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
    }
    return scope


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


class TestCredentialsMiddleware:
    """Test CredentialsMiddleware sets context from request headers."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sets_token_from_x_mpt_authorization(self):
        """X-MPT-Authorization header is normalized and set in _current_token for the request."""
        app = CredentialsMiddleware(_capture_context_app)
        scope = _make_scope(
            headers=[
                [b"x-mpt-authorization", b"Bearer idt:TKN-A-B:SECRET"],
                [b"content-type", b"application/json"],
            ]
        )
        body_chunks = []

        async def send(message):
            if message.get("type") == "http.response.body":
                body_chunks.append(message.get("body", b""))

        await app(scope, _receive, send)
        body = b"".join(body_chunks).decode()
        assert "token='idt:TKN-A-B:SECRET'" in body or 'token="idt:TKN-A-B:SECRET"' in body
        assert _current_token.get() is None  # reset in finally

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sets_endpoint_from_x_mpt_endpoint(self):
        """X-MPT-Endpoint header is set in _current_endpoint for the request."""
        app = CredentialsMiddleware(_capture_context_app)
        scope = _make_scope(
            headers=[
                [b"x-mpt-authorization", b"idt:TKN-X:Y"],
                [b"x-mpt-endpoint", b"https://api.example.com"],
            ]
        )
        body_chunks = []

        async def send(message):
            if message.get("type") == "http.response.body":
                body_chunks.append(message.get("body", b""))

        await app(scope, _receive, send)
        body = b"".join(body_chunks).decode()
        assert "endpoint='https://api.example.com'" in body or 'endpoint="https://api.example.com"' in body

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sets_validate_fresh_from_header(self):
        """X-MPT-Validate-Fresh: true sets _current_validate_fresh for the request."""
        app = CredentialsMiddleware(_capture_context_app)
        scope = _make_scope(
            headers=[
                [b"x-mpt-authorization", b"idt:TKN-X:Y"],
                [b"x-mpt-validate-fresh", b"true"],
            ]
        )
        body_chunks = []

        async def send(message):
            if message.get("type") == "http.response.body":
                body_chunks.append(message.get("body", b""))

        await app(scope, _receive, send)
        body = b"".join(body_chunks).decode()
        assert "validate_fresh=True" in body

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_auth_header_leaves_token_none(self):
        """When X-MPT-Authorization is missing, token in context is None."""
        app = CredentialsMiddleware(_capture_context_app)
        scope = _make_scope(headers=[[b"content-type", b"application/json"]])

        body_chunks = []

        async def send(message):
            if message.get("type") == "http.response.body":
                body_chunks.append(message.get("body", b""))

        await app(scope, _receive, send)
        body = b"".join(body_chunks).decode()
        assert "token=None" in body

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        """Non-http scope is passed to app without setting context."""
        call_count = 0

        async def passthrough_app(scope, receive, send):
            nonlocal call_count
            call_count += 1
            assert scope["type"] == "lifespan"
            await send({"type": "lifespan.startup.complete"})

        app = CredentialsMiddleware(passthrough_app)
        scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

        async def receive():
            return {"type": "lifespan.shutdown"}

        async def send(msg):
            pass

        await app(scope, receive, send)
        assert call_count == 1
