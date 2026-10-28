import pytest
from fastmcp import Client

from mpt_mcp.config import config
from mpt_mcp.server import mcp as http_mcp
from mpt_mcp.server_stdio import DEBUG_TAG, mcp

DEBUG_TOOLS = {"marketplace_cache_info", "marketplace_refresh_cache"}


@pytest.fixture
def debug_tools_disabled(restore_debug_tools):
    mcp.disable(tags={DEBUG_TAG})


@pytest.fixture
def debug_tools_enabled(restore_debug_tools):
    mcp.enable(tags={DEBUG_TAG})


@pytest.fixture
def restore_debug_tools():
    yield
    # Back to the visibility the server sets from DEBUG at import time
    (mcp.enable if config.debug else mcp.disable)(tags={DEBUG_TAG})


async def test_production_tools_exist():
    expected_tools = {
        "marketplace_query",
        "marketplace_resources",
        "marketplace_resource_info",
        "marketplace_resource_schema",
        "marketplace_audit_fields",
    }

    result = {tool.name for tool in await mcp.list_tools()}

    assert expected_tools <= result


@pytest.mark.usefixtures("debug_tools_disabled")
async def test_debug_tools_hidden_without_debug():
    result = {tool.name for tool in await mcp.list_tools()}

    assert not result & DEBUG_TOOLS


@pytest.mark.usefixtures("debug_tools_disabled")
async def test_debug_tools_not_callable_without_debug():
    async with Client(mcp) as client:
        result = await client.call_tool("marketplace_cache_info", {}, raise_on_error=False)

    assert result.is_error


@pytest.mark.usefixtures("debug_tools_enabled")
async def test_debug_tools_listed_with_debug():
    result = {tool.name for tool in await mcp.list_tools()}

    assert result >= DEBUG_TOOLS


async def test_http_server_adds_documentation_tools():
    stdio_tools = {tool.name for tool in await mcp.list_tools()}

    result = {tool.name for tool in await http_mcp.list_tools()} - stdio_tools

    assert result >= {"marketplace_docs_index", "marketplace_docs_list", "marketplace_docs_read"}
