"""
SoftwareOne Marketplace MCP Server
A Model Context Protocol server for the SoftwareOne Marketplace API
"""

__version__ = "2.0.0"
__author__ = "SoftwareOne"

from .server_stdio import mcp
from .api_client import APIClient
from .config import config
from .cache_manager import CacheManager
from .openapi_parser import OpenAPIParser

__all__ = [
    "mcp",
    "APIClient",
    "config",
    "CacheManager",
    "OpenAPIParser",
]


