from mpt_mcp.mcp_server import create_mcp_server


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
