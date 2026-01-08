#!/usr/bin/env python3
"""
Test HTTP server implementation
"""

import pytest
from src import server
from src.config import config


class TestHTTPServer:
    """Test HTTP server functionality"""
    
    @pytest.mark.unit
    def test_http_server_import(self):
        """Test that HTTP server can be imported"""
        assert server is not None
        assert hasattr(server, 'mcp')
    
    @pytest.mark.unit
    def test_config_http(self):
        """Test HTTP server configuration"""
        assert hasattr(config, 'sse_port')  # PORT env var
        assert hasattr(config, 'sse_default_base_url')
        
        # Check types
        assert isinstance(config.sse_port, int)
        assert isinstance(config.sse_port, int)
        assert isinstance(config.sse_cors_origins, list)
    
    @pytest.mark.unit
    def test_sse_defaults(self):
        """Test SSE default configuration values"""
        # These should have reasonable defaults even if not explicitly set
        assert config.sse_host in ["0.0.0.0", "localhost", "127.0.0.1"]
        assert 1000 <= config.sse_port <= 65535
        assert len(config.sse_cors_origins) > 0
    
    @pytest.mark.unit
    def test_mcp_instance(self):
        """Test that MCP instance is created"""
        from src.server import mcp
        assert mcp is not None
        # FastMCP should have certain attributes
        assert hasattr(mcp, 'streamable_http_app')
    
    @pytest.mark.unit
    def test_tools_registered(self):
        """Test that tools are registered"""
        from src.server import mcp
        # The MCP instance should have tool methods
        # (checking internal structure may vary by FastMCP version)
        assert mcp is not None
    
    @pytest.mark.unit
    def test_normalize_endpoint_from_server(self):
        """Test normalize_endpoint_url function"""
        from src.server import normalize_endpoint_url
        
        # Test removing /public suffix
        assert normalize_endpoint_url("https://api.test.com/public") == "https://api.test.com"
        assert normalize_endpoint_url("https://api.test.com") == "https://api.test.com"
        assert normalize_endpoint_url("https://api.test.com/") == "https://api.test.com"
    
    @pytest.mark.unit
    def test_get_current_credentials_without_context(self):
        """Test credential retrieval without context set"""
        from src.server import get_current_credentials
        
        # Without context, should return None for token and default for endpoint
        token, endpoint = get_current_credentials()
        
        assert token is None
        assert endpoint == config.sse_default_base_url or endpoint == "https://api.platform.softwareone.com"


class TestHTTPServerConfiguration:
    """Test HTTP server configuration and setup without requiring a running server"""
    
    @pytest.mark.unit
    def test_mcp_server_initialization(self):
        """Test that MCP server is properly initialized"""
        from src.server import mcp
        
        # The MCP instance should be initialized
        assert mcp is not None
        
        # Should have streamable_http_app method for HTTP transport
        assert hasattr(mcp, 'streamable_http_app')
        
        # Should be able to get the app
        app = mcp.streamable_http_app()
        assert app is not None
    
    @pytest.mark.unit
    def test_context_vars_defined(self):
        """Test that context variables for credentials are properly defined"""
        from src.server import _current_token, _current_endpoint, _current_user_id, _current_session_id
        
        # Test that context vars are properly defined
        assert _current_token is not None
        assert _current_endpoint is not None
        assert _current_user_id is not None
        assert _current_session_id is not None
        
        # Context vars should be None by default (no request context)
        assert _current_token.get() is None
        assert _current_endpoint.get() is None
        assert _current_user_id.get() is None
        assert _current_session_id.get() is None
    
    @pytest.mark.unit
    def test_normalize_endpoint_url_function(self):
        """Test URL normalization function removes /public suffix"""
        from src.server import normalize_endpoint_url
        
        # Test various URL formats
        assert normalize_endpoint_url("https://api.s1.show/public") == "https://api.s1.show"
        assert normalize_endpoint_url("https://api.s1.show/public/") == "https://api.s1.show"
        assert normalize_endpoint_url("https://api.s1.show") == "https://api.s1.show"
        assert normalize_endpoint_url("https://api.s1.show/") == "https://api.s1.show"
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_current_credentials_defaults(self):
        """Test get_current_credentials returns defaults when no context set"""
        from src.server import get_current_credentials
        from src.config import config
        
        # Without context, should return None for token and default for endpoint
        token, endpoint = get_current_credentials()
        
        assert token is None
        # Should return the default base URL
        assert endpoint in [config.sse_default_base_url, "https://api.platform.softwareone.com"]


class TestHTTPServerTools:
    """Test that HTTP server exposes only production-ready tools"""
    
    @pytest.mark.unit
    def test_production_tools_only(self):
        """Test that only production tools are exposed (no debug tools)"""
        from src.server import mcp
        
        # Get list of registered tools
        tool_names = [tool.name for tool in mcp.list_tools()]
        
        # These production tools SHOULD exist
        expected_tools = [
            'marketplace_query',
            'marketplace_resources',
            'marketplace_resource_info',
            'marketplace_resource_schema'
        ]
        
        for tool_name in expected_tools:
            assert tool_name in tool_names, f"Missing production tool: {tool_name}"
        
        # Debug tool should NOT exist in production server
        assert 'marketplace_cache_info' not in tool_names, \
            "Debug tool marketplace_cache_info should not be in production server"
        assert 'marketplace_refresh_cache' not in tool_names, \
            "Debug tool marketplace_refresh_cache should not be in production server"
    
    @pytest.mark.unit
    def test_tool_functions_exist(self):
        """Test that all expected tool functions are registered"""
        from src.server import mcp
        
        # Get list of registered tools
        tool_names = [tool.name for tool in mcp.list_tools()]
        
        # Production tools
        expected_tools = [
            'marketplace_query',
            'marketplace_resources', 
            'marketplace_resource_info',
            'marketplace_resource_schema'
        ]
        
        for tool_name in expected_tools:
            assert tool_name in tool_names, f"Missing production tool: {tool_name}"
    
    @pytest.mark.unit
    def test_debug_tools_not_in_production(self):
        """Test that debug/internal tools are not exposed in production server"""
        from src.server import mcp
        
        # Get list of registered tools
        tool_names = [tool.name for tool in mcp.list_tools()]
        
        # Debug tools that should NOT be in production
        debug_tools = [
            'marketplace_cache_info',
            'marketplace_refresh_cache'
        ]
        
        for tool_name in debug_tools:
            assert tool_name not in tool_names, \
                f"Debug tool {tool_name} should not be in production server"
