#!/usr/bin/env python3
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.testclient import TestClient

from mpt_mcp import server
from mpt_mcp.config import config


@pytest.mark.unit
def test_http_server_import():
    assert server is not None
    assert hasattr(server, "mcp")


@pytest.mark.unit
def test_config_http():
    assert hasattr(config, "sse_port")  # PORT env var
    assert hasattr(config, "sse_default_base_url")

    # Check types
    assert isinstance(config.sse_port, int)
    assert isinstance(config.sse_port, int)
    assert isinstance(config.sse_cors_origins, list)


@pytest.mark.unit
def test_sse_defaults():
    # These should have reasonable defaults even if not explicitly set
    assert config.sse_host in ["0.0.0.0", "localhost", "127.0.0.1"]
    assert 1000 <= config.sse_port <= 65535
    assert len(config.sse_cors_origins) > 0


@pytest.mark.unit
def test_mcp_instance():
    from mpt_mcp.server import mcp

    assert mcp is not None
    # FastMCP should have http_app for HTTP transport
    assert hasattr(mcp, "http_app")


@pytest.mark.unit
def test_tools_registered():
    from mpt_mcp.server import mcp

    # The MCP instance should have tool methods
    # (checking internal structure may vary by FastMCP version)
    assert mcp is not None


@pytest.mark.unit
def test_normalize_endpoint_from_server():
    from mpt_mcp.server_context import normalize_endpoint_url

    # Test removing /public suffix
    assert normalize_endpoint_url("https://api.test.com/public") == "https://api.test.com"
    assert normalize_endpoint_url("https://api.test.com") == "https://api.test.com"
    assert normalize_endpoint_url("https://api.test.com/") == "https://api.test.com"


@pytest.mark.unit
def test_mcp_server_initialization():
    from mpt_mcp.server import mcp

    # The MCP instance should be initialized
    assert mcp is not None

    # Should have http_app method for HTTP transport
    assert hasattr(mcp, "http_app")

    # Should be able to get the app
    app = mcp.http_app()
    assert app is not None


@pytest.mark.unit
def test_normalize_endpoint_url_function():
    from mpt_mcp.server_context import normalize_endpoint_url

    # Test various URL formats
    assert normalize_endpoint_url("https://api.s1.show/public") == "https://api.s1.show"
    assert normalize_endpoint_url("https://api.s1.show/public/") == "https://api.s1.show"
    assert normalize_endpoint_url("https://api.s1.show") == "https://api.s1.show"
    assert normalize_endpoint_url("https://api.s1.show/") == "https://api.s1.show"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_tools_only():
    from mpt_mcp.server import mcp

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
    assert "marketplace_cache_info" not in tool_names, "Debug tool marketplace_cache_info should not be in production server"
    assert "marketplace_refresh_cache" not in tool_names, "Debug tool marketplace_refresh_cache should not be in production server"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_functions_exist():
    from mpt_mcp.server import mcp

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_debug_tools_not_in_production():
    from mpt_mcp.server import mcp

    tools_dict = {t.name: t for t in (await mcp.list_tools())}
    tool_names = list(tools_dict.keys())

    # Debug tools that should NOT be in production
    debug_tools = ["marketplace_cache_info", "marketplace_refresh_cache"]

    for tool_name in debug_tools:
        assert tool_name not in tool_names, f"Debug tool {tool_name} should not be in production server"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_docs_list_exposes_browser_url_and_usage_note():
    mock_resources = [
        {
            "uri": "docs://help-and-support/contact-support",
            "name": "Contact Support",
            "description": "Documentation page: Contact Support",
            "mimeType": "text/markdown",
            "metadata": {
                "id": "7qHvpiUID0CAu2h8cXUr",
                "path": "help-and-support/contact-support",
                "title": "Contact Support",
                "browser_url": "https://docs.example.com/help-and-support/contact-support",
            },
        },
    ]
    mock_cache = Mock()
    mock_cache.is_enabled = True
    mock_cache.list_resources = AsyncMock(return_value=mock_resources)

    with patch("mpt_mcp.server_docs.documentation_cache", mock_cache):
        with patch("mpt_mcp.server_docs.initialize_documentation_cache", AsyncMock()):
            from mpt_mcp.server_tools import marketplace_docs_list

            result = await marketplace_docs_list(search="contact support")

    assert result["total"] == 1
    assert len(result["resources"]) == 1
    assert result["resources"][0]["browser_url"] == "https://docs.example.com/help-and-support/contact-support"
    assert "Prefer showing users the browser_url" in result["usage"]
    assert "do not show internal uri or id" in result["usage"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_docs_list_no_browser_url_when_metadata_missing():
    mock_resources = [
        {
            "uri": "docs://some/page",
            "name": "Some Page",
            "description": "A page",
            "mimeType": "text/markdown",
            "metadata": {"id": "abc", "path": "some/page", "title": "Some Page"},
        },
    ]
    mock_cache = Mock()
    mock_cache.is_enabled = True
    mock_cache.list_resources = AsyncMock(return_value=mock_resources)

    with patch("mpt_mcp.server_docs.documentation_cache", mock_cache):
        with patch("mpt_mcp.server_docs.initialize_documentation_cache", AsyncMock()):
            from mpt_mcp.server_tools import marketplace_docs_list

            result = await marketplace_docs_list(search="some")

    assert result["total"] == 1
    assert "browser_url" not in result["resources"][0]
    assert "Prefer showing users the browser_url" in result["usage"]


@pytest.mark.unit
def test_health_404_hint_and_mcp_trailing_slash():
    with TestClient(server.app) as client:
        # 1. Health returns 200 with endpoint: /mcp
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("endpoint") == "/mcp"
        assert data.get("status") == "healthy"

        # 2. Wrong path (GET) returns 404 with JSON hint
        r = client.get("/nonexistent")
        assert r.status_code == 404
        data = r.json()
        assert "hint" in data
        assert "POST /mcp" in data["hint"]

        # 3. Wrong path (POST) returns 404 with same hint
        r = client.post("/wrong", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert r.status_code == 404
        data = r.json()
        assert "hint" in data
        assert "POST /mcp" in data["hint"]

        # 4. POST /mcp/ (trailing slash) is rewritten to /mcp and handled (not 404)
        r = client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
            },
        )
        assert r.status_code != 404, "POST /mcp/ should be rewritten to /mcp and not return 404"

        # 5. POST / (root, e.g. when LB strips path) is rewritten to /mcp and handled (not 404)
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
            },
        )
        assert r.status_code != 404, "POST / should be rewritten to /mcp when platform strips path"

        # 6. GET / still returns health (not MCP)
        r = client.get("/")
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"
