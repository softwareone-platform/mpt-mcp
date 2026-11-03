from http import HTTPStatus

import pytest
from starlette.testclient import TestClient

from mpt_mcp.runtime.http import create_http_app
from mpt_mcp.server import create_mcp_server


@pytest.fixture
def initialize_request():
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }


@pytest.fixture
def http_client():
    app = create_http_app(create_mcp_server(transport="stdio"))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("path", ["/health", "/"])
def test_get_health_returns_status(http_client, path):
    result = http_client.get(path)

    assert (result.status_code, result.json()) == (
        200,
        {
            "status": "healthy",
            "service": "mpt-mcp-http",
            "transport": "streamable-http",
            "endpoint": "/mcp",
        },
    )


@pytest.mark.parametrize(("method", "path"), [("GET", "/nonexistent"), ("POST", "/wrong")])
def test_unknown_path_returns_mcp_hint(http_client, method, path):
    result = http_client.request(
        method, path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )

    assert result.status_code == HTTPStatus.NOT_FOUND
    assert "POST /mcp" in result.json()["hint"]


@pytest.mark.parametrize("path", ["/mcp/", "/"])
def test_post_is_rewritten_to_mcp_endpoint(http_client, initialize_request, path):
    result = http_client.post(
        path, json=initialize_request, headers={"Accept": "application/json, text/event-stream"}
    )

    assert result.status_code != HTTPStatus.NOT_FOUND
