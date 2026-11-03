from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from mpt_mcp.config import config
from mpt_mcp.documentation import lifespan
from mpt_mcp.documentation.server import DOCUMENTATION_CACHE_UNAVAILABLE_MSG
from mpt_mcp.mcp_server import create_mcp_server

DEBUG_TOOLS = {"marketplace_cache_info", "marketplace_refresh_cache", "marketplace_resources_info"}


@pytest.fixture
def production_server(monkeypatch):
    monkeypatch.setattr(config, "debug", False)
    return create_mcp_server(transport="stdio")


@pytest.fixture
def debug_server(monkeypatch):
    monkeypatch.setattr(config, "debug", True)
    return create_mcp_server(transport="stdio")


async def test_production_tools_exist(production_server):
    expected_tools = {
        "marketplace_query",
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


async def test_every_tool_has_an_output_schema(debug_server):
    tools = await debug_server.list_tools()

    result = [tool.name for tool in tools if not tool.output_schema.get("properties")]

    assert not result


async def test_tool_result_matches_its_output_schema(debug_server):
    async with Client(debug_server) as client:
        result = await client.call_tool("marketplace_cache_info", {})

    assert set(result.structured_content) == {"cache_status", "cache_info", "note"}


async def test_prompts_registered(production_server):
    result = {prompt.name for prompt in await production_server.list_prompts()}

    assert result == {
        "agreements_for_client",
        "orders_by_status",
        "orders_for_product",
        "products_by_vendor",
        "recent_orders",
        "search_buyers",
        "search_products",
        "subscriptions_due",
        "subscriptions_for_product",
    }


async def test_prompt_renders_query_request(production_server):
    async with Client(production_server) as client:
        result = await client.get_prompt("search_products", {"name": "Adobe"})

    assert "rql=ilike(name,*Adobe*)" in result.messages[0].content.text


async def test_tool_failure_is_an_error_result(production_server, monkeypatch):
    monkeypatch.setattr(lifespan, "initialize_documentation_cache", AsyncMock())
    monkeypatch.setattr(lifespan, "documentation_cache", None)

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


async def test_transports_serve_the_same_tools():
    http_tools = {tool.name for tool in await create_mcp_server(transport="http").list_tools()}

    result = {tool.name for tool in await create_mcp_server(transport="stdio").list_tools()}

    assert result == http_tools


async def test_transports_serve_the_same_resources():
    http_server = create_mcp_server(transport="http")
    http_templates = {
        template.uri_template for template in await http_server.list_resource_templates()
    }
    stdio_server = create_mcp_server(transport="stdio")

    result = {template.uri_template for template in await stdio_server.list_resource_templates()}

    assert result == http_templates
