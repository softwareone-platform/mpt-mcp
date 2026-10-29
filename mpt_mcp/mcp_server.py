from fastmcp import FastMCP

from mpt_mcp.analytics import AnalyticsMiddleware, analytics_lifespan
from mpt_mcp.config import config
from mpt_mcp.server_middleware import RequestContextMiddleware
from mpt_mcp.server_resources import register_resources
from mpt_mcp.server_tools import DEBUG_TAG, register_tools

SERVER_NAME = "softwareone-marketplace"


def create_mcp_server(*, analytics: bool) -> FastMCP:
    """
    Create the MCP server with every tool and resource, served by both transports.

    Args:
        analytics: Record usage events in the analytics database (HTTP server only)

    Returns:
        MCP server, with the debug tools disabled unless DEBUG=true
    """
    # RequestContextMiddleware runs first so analytics and tool logs carry the caller's log prefix
    if analytics:
        mcp = FastMCP(
            SERVER_NAME,
            lifespan=analytics_lifespan,
            middleware=[RequestContextMiddleware(), AnalyticsMiddleware()],
        )
    else:
        mcp = FastMCP(SERVER_NAME, middleware=[RequestContextMiddleware()])
    register_tools(mcp)
    register_resources(mcp)
    # Debug tools are only listed and callable in development
    if not config.debug:
        mcp.disable(tags={DEBUG_TAG})
    return mcp
