from mpt_mcp import server_stdio
from mpt_mcp.server import mcp as http_mcp


async def test_transports_serve_the_same_tools():
    http_tools = {tool.name for tool in await http_mcp.list_tools()}

    result = {tool.name for tool in await server_stdio.mcp.list_tools()}

    assert result == http_tools


async def test_transports_serve_the_same_resources():
    http_templates = {
        template.uri_template for template in await http_mcp.list_resource_templates()
    }

    result = {
        template.uri_template for template in await server_stdio.mcp.list_resource_templates()
    }

    assert result == http_templates
