import logging
from http import HTTPStatus

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
# Paths some proxies send MCP requests to: a load balancer that strips the path sends POST /
MCP_PATH_ALIASES = frozenset(("/", "/mcp/"))
HEALTH_PATHS = ("/", "/health")
HEALTH_RESPONSE = {
    "status": "healthy",
    "service": "mpt-mcp-http",
    "transport": "streamable-http",
    "endpoint": MCP_PATH,
}
USER_AGENT_LOG_LENGTH = 80


class MCPPathMiddleware:
    """Send POST / and POST /mcp/ to the MCP endpoint, for proxies that strip or add the path."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Rewrite the path of an MCP POST sent to an alias of /mcp."""
        is_aliased_post = (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] in MCP_PATH_ALIASES
        )
        if is_aliased_post:
            scope = {**scope, "path": MCP_PATH}
        await self.app(scope, receive, send)


def health(request: Request) -> JSONResponse:
    """Report that the server is up and where its MCP endpoint is."""
    return JSONResponse(HEALTH_RESPONSE)


def not_found(request: Request, exc: Exception) -> JSONResponse:
    """Return a hint to the MCP endpoint for unknown paths, and the detail of other errors."""
    status_code = exc.status_code if isinstance(exc, HTTPException) else HTTPStatus.NOT_FOUND
    if status_code != HTTPStatus.NOT_FOUND:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return JSONResponse({"detail": detail}, status_code=status_code)

    # Logged so the deployment shows the path that arrived, e.g. when a proxy strips it
    logger.warning(
        "404 %s path=%r mcp_session_id=%s ua=%r",
        request.method,
        request.url.path,
        "yes" if request.headers.get("mcp-session-id") else "no",
        (request.headers.get("user-agent") or "")[:USER_AGENT_LOG_LENGTH],
    )
    return JSONResponse(
        {
            "error": "Not found",
            "hint": "MCP endpoint is POST /mcp (no trailing slash). Ensure MCP_SERVER_URL ends "
            "with /mcp and the MCP server is running. See README Troubleshooting.",
        },
        status_code=HTTPStatus.NOT_FOUND,
    )


def create_http_app(mcp: FastMCP) -> Starlette:
    """
    Create the ASGI app of the HTTP transport.

    The app is stateless: no server-side MCP sessions, so any instance behind a load balancer
    serves any request.

    Args:
        mcp: MCP server to serve at /mcp

    Returns:
        Starlette app with the MCP endpoint, the health check and the not found hint
    """
    for health_path in HEALTH_PATHS:
        mcp.custom_route(health_path, methods=["GET"])(health)
    app = mcp.http_app(
        path=MCP_PATH, stateless_http=True, middleware=[Middleware(MCPPathMiddleware)]
    )
    app.add_exception_handler(HTTPException, not_found)
    return app
