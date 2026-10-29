from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from mpt_mcp import server_stdio
from mpt_mcp.config import config
from mpt_mcp.server import mcp as http_mcp

DEBUG_TOOLS = {"marketplace_cache_info", "marketplace_refresh_cache"}


@pytest.fixture
def debug_tools_disabled(restore_debug_tools):
    server_stdio.mcp.disable(tags={server_stdio.DEBUG_TAG})


@pytest.fixture
def debug_tools_enabled(restore_debug_tools):
    server_stdio.mcp.enable(tags={server_stdio.DEBUG_TAG})


@pytest.fixture
def restore_debug_tools():
    yield
    # Back to the visibility the server sets from DEBUG at import time
    (server_stdio.mcp.enable if config.debug else server_stdio.mcp.disable)(
        tags={server_stdio.DEBUG_TAG}
    )


async def test_production_tools_exist():
    expected_tools = {
        "marketplace_query",
        "marketplace_resources",
        "marketplace_resource_info",
        "marketplace_resource_schema",
        "marketplace_audit_fields",
    }

    result = {tool.name for tool in await server_stdio.mcp.list_tools()}

    assert expected_tools <= result


@pytest.mark.usefixtures("debug_tools_disabled")
async def test_debug_tools_hidden_without_debug():
    result = {tool.name for tool in await server_stdio.mcp.list_tools()}

    assert not result & DEBUG_TOOLS


@pytest.mark.usefixtures("debug_tools_disabled")
async def test_debug_tools_not_callable_without_debug():
    async with Client(server_stdio.mcp) as client:
        result = await client.call_tool("marketplace_cache_info", {}, raise_on_error=False)

    assert result.is_error


@pytest.mark.usefixtures("debug_tools_enabled")
async def test_debug_tools_listed_with_debug():
    result = {tool.name for tool in await server_stdio.mcp.list_tools()}

    assert result >= DEBUG_TOOLS


async def test_http_server_adds_documentation_tools():
    stdio_tools = {tool.name for tool in await server_stdio.mcp.list_tools()}

    result = {tool.name for tool in await http_mcp.list_tools()} - stdio_tools

    assert result >= {"marketplace_docs_index", "marketplace_docs_list", "marketplace_docs_read"}


@pytest.fixture
def stdio_state(monkeypatch):
    # initialize_server sets module globals; monkeypatch restores them after the test
    for name in (
        "api_client",
        "cache_manager",
        "endpoints_registry",
        "openapi_spec",
        "_initialized",
    ):
        monkeypatch.setattr(server_stdio, name, getattr(server_stdio, name))
    monkeypatch.setattr(config, "marketplace_api_base_url", "https://api.test.com/public")
    monkeypatch.setattr(config, "marketplace_api_token", "idt:TKN-1234-5678:SECRET")
    fetch = AsyncMock(return_value={"paths": {}})
    monkeypatch.setattr(server_stdio, "fetch_with_cache", fetch)
    return fetch


async def test_initialize_server_loads_spec_of_base_url(stdio_state):
    await server_stdio.initialize_server(force_refresh=True)  # act

    assert stdio_state.call_args.kwargs["url"] == "https://api.test.com/public/v1/openapi.json"
