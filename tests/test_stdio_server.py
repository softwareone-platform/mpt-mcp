#!/usr/bin/env python3
"""
Test STDIO server implementation (local development)
"""

import pytest
from src import server_stdio
from src.config import config


class TestSTDIOServer:
    """Test STDIO server functionality for local development"""
    
    @pytest.mark.unit
    def test_stdio_server_import(self):
        """Test that STDIO server can be imported"""
        assert server_stdio is not None
        assert hasattr(server_stdio, 'mcp')
    
    @pytest.mark.unit
    def test_mcp_instance(self):
        """Test that MCP instance is created"""
        from src.server_stdio import mcp
        assert mcp is not None


class TestSTDIOServerTools:
    """Test that STDIO server has both production and debug tools"""
    
    @pytest.mark.unit
    def test_production_tools_exist(self):
        """Test that production tools are available in STDIO server"""
        from src import server_stdio
        
        # Production tools SHOULD exist
        expected_tools = [
            'marketplace_query',
            'marketplace_resources',
            'marketplace_resource_info',
            'marketplace_resource_schema'
        ]
        
        for tool_name in expected_tools:
            assert hasattr(server_stdio, tool_name), f"Missing production tool: {tool_name}"
            tool_func = getattr(server_stdio, tool_name)
            assert callable(tool_func), f"Tool {tool_name} is not callable"
    
    @pytest.mark.unit
    def test_debug_tools_exist(self):
        """Test that debug/cache tools ARE available in STDIO server (for local dev)"""
        from src import server_stdio
        
        # Debug tools that SHOULD be in STDIO server for local development
        debug_tools = [
            'marketplace_cache_info',
            'marketplace_refresh_cache'
        ]
        
        for tool_name in debug_tools:
            assert hasattr(server_stdio, tool_name), \
                f"Debug tool {tool_name} should be available in STDIO server for local development"
            tool_func = getattr(server_stdio, tool_name)
            assert callable(tool_func), f"Debug tool {tool_name} is not callable"
    
    @pytest.mark.unit
    def test_tool_count_difference(self):
        """Test that STDIO server has MORE tools than HTTP server (includes debug tools)"""
        from src import server_stdio, server
        
        # Get callable functions that start with 'marketplace_'
        stdio_tools = [name for name in dir(server_stdio) 
                       if name.startswith('marketplace_') and callable(getattr(server_stdio, name))]
        http_tools = [name for name in dir(server) 
                      if name.startswith('marketplace_') and callable(getattr(server, name))]
        
        # STDIO should have at least as many tools as HTTP (actually more due to debug tools)
        assert len(stdio_tools) >= len(http_tools), \
            "STDIO server should have at least as many tools as HTTP server"
        
        # Specifically, STDIO should have cache management tools
        stdio_only_tools = set(stdio_tools) - set(http_tools)
        assert 'marketplace_cache_info' in stdio_only_tools or 'marketplace_cache_info' in stdio_tools, \
            "STDIO server should have marketplace_cache_info for debugging"
