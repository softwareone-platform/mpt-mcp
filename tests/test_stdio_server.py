#!/usr/bin/env python3
"""
Test STDIO server implementation (local development)
"""

import pytest

from src import server_stdio


class TestSTDIOServer:
    """Test STDIO server functionality for local development"""

    @pytest.mark.unit
    def test_stdio_server_import(self):
        """Test that STDIO server can be imported"""
        assert server_stdio is not None
        assert hasattr(server_stdio, "mcp")

    @pytest.mark.unit
    def test_mcp_instance(self):
        """Test that MCP instance is created"""
        from src.server_stdio import mcp

        assert mcp is not None


class TestSTDIOServerTools:
    """Test that STDIO server has both production and debug tools"""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_production_tools_exist(self):
        """Test that production tools are registered in STDIO server"""
        from src.server_stdio import mcp

        # Get list of registered tools (async)
        tools = await mcp.list_tools()
        tool_names = [tool.name for tool in tools]

        # Production tools SHOULD exist
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
    async def test_debug_tools_exist(self):
        """Test that debug/cache tools ARE available in STDIO server (for local dev)"""
        from src.server_stdio import mcp

        # Get list of registered tools (async)
        tools = await mcp.list_tools()
        tool_names = [tool.name for tool in tools]

        # Debug tools that SHOULD be in STDIO server for local development
        debug_tools = ["marketplace_cache_info", "marketplace_refresh_cache"]

        for tool_name in debug_tools:
            assert tool_name in tool_names, f"Debug tool {tool_name} should be available in STDIO server for local development"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tool_count_difference(self):
        """Test that HTTP server has documentation tools that STDIO doesn't have"""
        from src.server import mcp as http_mcp
        from src.server_stdio import mcp as stdio_mcp

        # Get tool counts (async)
        stdio_tools_list = await stdio_mcp.list_tools()
        http_tools_list = await http_mcp.list_tools()

        stdio_tools = [tool.name for tool in stdio_tools_list]
        http_tools = [tool.name for tool in http_tools_list]

        # HTTP server has documentation tools that STDIO doesn't need
        # Expected difference: marketplace_docs_index, marketplace_docs_list, marketplace_docs_read
        expected_http_only_tools = {"marketplace_docs_index", "marketplace_docs_list", "marketplace_docs_read"}

        http_only = set(http_tools) - set(stdio_tools)

        # HTTP should have at least the documentation tools
        assert expected_http_only_tools.issubset(http_only), f"HTTP server should have documentation tools. Expected at least {expected_http_only_tools}, got {http_only}"

        # Both should have core API tools
        core_tools = {"marketplace_query", "marketplace_resources", "marketplace_resource_info"}
        assert core_tools.issubset(set(stdio_tools)), f"STDIO server missing core tools: {core_tools - set(stdio_tools)}"
        assert core_tools.issubset(set(http_tools)), f"HTTP server missing core tools: {core_tools - set(http_tools)}"

        # STDIO should have cache management tools for debugging
        assert "marketplace_cache_info" in stdio_tools, "STDIO server should have marketplace_cache_info for debugging"
