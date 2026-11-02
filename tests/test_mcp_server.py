from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from mpt_mcp import server_docs
from mpt_mcp.config import config
from mpt_mcp.mcp_server import create_mcp_server
from mpt_mcp.server_tools import DOCUMENTATION_CACHE_UNAVAILABLE_MSG

DEBUG_TOOLS = {"marketplace_cache_info", "marketplace_refresh_cache", "marketplace_resources_info"}


@pytest.fixture
def production_server(monkeypatch):
    monkeypatch.setattr(config, "debug", False)
    return create_mcp_server(analytics=False)


@pytest.fixture
def debug_server(monkeypatch):
    monkeypatch.setattr(config, "debug", True)
    return create_mcp_server(analytics=False)


async def test_production_tools_exist(production_server):
    expected_tools = {
        "marketplace_query",
        "marketplace_quick_queries",
        "marketplace_resources",
        "marketplace_resource_info",
        "marketplace_resource_schema",
        "marketplace_audit_fields",
        "marketplace_docs_index",
        "marketplace_docs_list",
        "marketplace_docs_read",
    }

    result = {tool.name for tool in await production_server.list_tools()}

    assert result == expected_tools


async def test_debug_tools_not_callable_without_debug(production_server):
    async with Client(production_server) as client:
        result = await client.call_tool("marketplace_cache_info", {}, raise_on_error=False)

    assert result.is_error


async def test_debug_tools_listed_with_debug(debug_server):
    result = {tool.name for tool in await debug_server.list_tools()}

    assert result >= DEBUG_TOOLS


async def test_every_tool_has_a_description(debug_server):
    tools = await debug_server.list_tools()

    result = [tool.name for tool in tools if not tool.description]

    assert not result


async def test_every_tool_has_a_title(debug_server):
    tools = await debug_server.list_tools()

    result = [tool.name for tool in tools if not tool.title]

    assert not result


async def test_only_refresh_cache_is_not_read_only(debug_server):
    tools = await debug_server.list_tools()

    result = [tool.name for tool in tools if not tool.annotations.read_only_hint]

    assert result == ["marketplace_refresh_cache"]


async def test_instructions_name_every_production_tool(production_server):
    tools = await production_server.list_tools()

    result = [tool.name for tool in tools if tool.name not in production_server.instructions]

    assert not result


async def test_tool_failure_is_an_error_result(production_server, monkeypatch):
    monkeypatch.setattr(server_docs, "initialize_documentation_cache", AsyncMock())
    monkeypatch.setattr(server_docs, "documentation_cache", None)

    async with Client(production_server) as client:
        result = await client.call_tool(
            "marketplace_docs_read", {"uri": "docs://readme"}, raise_on_error=False
        )

    assert (result.is_error, result.content[0].text) == (True, DOCUMENTATION_CACHE_UNAVAILABLE_MSG)


async def test_tools_hide_the_call_context(debug_server):
    tools = await debug_server.list_tools()

    result = [tool.name for tool in tools if "call_context" in tool.parameters["properties"]]

    assert not result


async def test_resources_registered(production_server):
    resources = await production_server.list_resources()
    templates = await production_server.list_resource_templates()

    result = (
        {str(resource.uri) for resource in resources},
        {template.uri_template for template in templates},
    )

    assert result == ({"api://openapi.json"}, {"docs://{path*}"})
