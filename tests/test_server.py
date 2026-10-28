import pytest
from starlette.testclient import TestClient

from mpt_mcp.server import app, mcp


async def test_production_tools_only():

    tools_dict = {t.name: t for t in (await mcp.list_tools())}
    tool_names = list(tools_dict.keys())

    # These production tools SHOULD exist
    expected_tools = [
        "marketplace_query",
        "marketplace_resources",
        "marketplace_resource_info",
        "marketplace_resource_schema",
    ]

    for tool_name in expected_tools:
        assert tool_name in tool_names, f"Missing production tool: {tool_name}"

    # Debug tool should NOT exist in production server
    assert "marketplace_cache_info" not in tool_names, (
        "Debug tool marketplace_cache_info should not be in production server"
    )
    assert "marketplace_refresh_cache" not in tool_names, (
        "Debug tool marketplace_refresh_cache should not be in production server"
    )


async def test_tool_functions_exist():

    tools_dict = {t.name: t for t in (await mcp.list_tools())}
    tool_names = list(tools_dict.keys())

    # Production tools
    expected_tools = [
        "marketplace_query",
        "marketplace_resources",
        "marketplace_resource_info",
        "marketplace_resource_schema",
    ]

    for tool_name in expected_tools:
        assert tool_name in tool_names, f"Missing production tool: {tool_name}"


async def test_debug_tools_not_in_production():

    tools_dict = {t.name: t for t in (await mcp.list_tools())}
    tool_names = list(tools_dict.keys())

    # Debug tools that should NOT be in production
    debug_tools = ["marketplace_cache_info", "marketplace_refresh_cache"]

    for tool_name in debug_tools:
        assert tool_name not in tool_names, (
            f"Debug tool {tool_name} should not be in production server"
        )


INITIALIZE_REQUEST = {
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
def test_unknown_path_returns_404_with_mcp_hint(http_client, method, path):
    result = http_client.request(
        method, path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )

    assert result.status_code == 404
    assert "POST /mcp" in result.json()["hint"]


@pytest.mark.parametrize("path", ["/mcp/", "/"])
def test_post_is_rewritten_to_mcp_endpoint(http_client, path):
    result = http_client.post(
        path, json=INITIALIZE_REQUEST, headers={"Accept": "application/json, text/event-stream"}
    )

    assert result.status_code != 404
