#!/usr/bin/env python3

import asyncio
import concurrent.futures
import logging
import os
import pathlib
import sys
import warnings

import uvicorn
from alembic.config import Config as AlembicConfig
from fastmcp import FastMCP
from fastmcp.resources import FunctionResource
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from alembic import command
from mpt_mcp import server_docs
from mpt_mcp.analytics import AnalyticsMiddleware, analytics_lifespan
from mpt_mcp.config import config
from mpt_mcp.log_config import configure_logging
from mpt_mcp.server_docs import initialize_documentation_cache
from mpt_mcp.server_middleware import RequestContextMiddleware
from mpt_mcp.server_resources import register_http_resources
from mpt_mcp.server_tools import register_http_tools

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.*deprecated.*")
configure_logging(logging.DEBUG if config.debug else logging.INFO)
logging.getLogger("fastmcp").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

server_port = int(os.getenv("PORT", "8080"))
server_host = "0.0.0.0"
logger.info(f"🌐 Configured for {server_host}:{server_port}")
# RequestContextMiddleware runs first so analytics and tool logs carry the caller's log prefix
mcp = FastMCP(
    "softwareone-marketplace",
    lifespan=analytics_lifespan,
    middleware=[RequestContextMiddleware(), AnalyticsMiddleware()],
)
register_http_tools(mcp)
register_http_resources(mcp)


async def _create_app():
    """Build the ASGI app (init + middleware). Used so uvicorn can load via 'mpt_mcp.server:app' for reload."""
    await initialize_documentation_cache()
    doc_cache = server_docs.documentation_cache
    doc_resource_count = 0
    if doc_cache and doc_cache.is_enabled:
        try:
            doc_list = await doc_cache.list_resources()
            for r in doc_list:
                uri = r.get("uri") or ""
                if not uri.startswith("docs://"):
                    continue
                name = r.get("name") or (r.get("metadata") or {}).get("title", uri)
                description = r.get("description") or f"Documentation: {name}"

                def _make_reader(cache, resource_uri: str):
                    async def _doc_reader() -> str:
                        content = await cache.get_resource(resource_uri)
                        return content or ""

                    return _doc_reader

                doc_resource = FunctionResource.from_function(
                    _make_reader(doc_cache, uri),
                    uri=uri,
                    name=name,
                    description=description,
                    mime_type="text/markdown",
                )
                mcp.add_resource(doc_resource)
                doc_resource_count += 1
            logger.info(f"📝 Registered {doc_resource_count} documentation resources for discovery")
        except Exception as e:
            logger.warning(f"⚠️  Could not register doc resources for discovery: {e}")
    else:
        logger.info(
            "ℹ️  Documentation resources: none (set GITBOOK_API_KEY and GITBOOK_SPACE_ID to enable). docs://{path} template is still available for reading when configured."
        )
    # Stateless HTTP always: no server-side sessions, so no 404 "Session not found" when load-balanced.
    # Docs cache is populated at startup and remains in memory for all requests in that process.
    starlette_app = mcp.http_app(stateless_http=True)
    # Route POST /mcp is registered by FastMCP here and never unregistered in this process.
    # Intermittent 404s are usually: path stripped to / (we rewrite POST / → /mcp), or traffic hitting an old revision during deploy.

    # Custom 404 response so clients see a clear hint when path is wrong (e.g. 404 on POST /mcp)
    def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 404:
            # Log so prod (e.g. Cloud Run) can see what path was received (helps when LB strips path)
            has_mcp_session_id = bool(
                request.headers.get("mcp-session-id") or request.headers.get("Mcp-Session-Id")
            )
            ua = (request.headers.get("user-agent") or "")[:80]
            logger.warning(
                f"⚠️ 404 {request.method} path={request.url.path!r} mcp_session_id={'yes' if has_mcp_session_id else 'no'} ua={ua!r}"
            )
            return JSONResponse(
                {
                    "error": "Not found",
                    "hint": "MCP endpoint is POST /mcp (no trailing slash). Ensure MCP_SERVER_URL ends with /mcp and the MCP server is running. See README Troubleshooting.",
                },
                status_code=404,
            )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    starlette_app.add_exception_handler(HTTPException, _http_exception_handler)

    class HealthCheckMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                request = Request(scope, receive)
                # Accept POST /mcp/ (trailing slash) by rewriting to /mcp so path matches FastMCP route
                if request.url.path == "/mcp/" and request.method == "POST":
                    scope = dict(scope)
                    scope["path"] = "/mcp"
                # When platform (e.g. LB/API Gateway) strips path, requests arrive as POST / ; treat as MCP
                if request.url.path == "/" and request.method == "POST":
                    scope = dict(scope)
                    scope["path"] = "/mcp"
                # Health only for GET (POST / is rewritten above and must go to MCP)
                if request.method == "GET" and request.url.path in ["/", "/health"]:
                    response = JSONResponse({
                        "status": "healthy",
                        "service": "mpt-mcp-http",
                        "transport": "streamable-http",
                        "endpoint": "/mcp",
                    })
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    final_app = HealthCheckMiddleware(starlette_app)
    logger.info(
        "✅ Middleware added: RequestContextMiddleware, AnalyticsMiddleware, HealthCheckMiddleware"
    )

    class AccessLogFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if hasattr(record, "args") and len(record.args) >= 3:
                path = str(record.args[2])
                if path in ["/mcp", "/health", "GET /health", "POST /mcp"]:
                    return False
            return True

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(AccessLogFilter())
    return final_app


def _build_app():
    """Build app once. Use asyncio.run() when no loop is running (main process); run in a thread when inside uvicorn worker (loop already running)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_create_app())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _create_app())
        return future.result()


app = _build_app()


def run_migrations():
    if not config.analytics_database_url:
        logger.info("⏩ Skipping migrations (analytics not configured)")
        return
    try:
        logger.info("🔄 Running database migrations...")
        project_root = pathlib.Path(__file__).parent.parent
        alembic_ini_path = project_root / "alembic.ini"
        alembic_dir = project_root / "alembic"
        alembic_cfg = AlembicConfig(str(alembic_ini_path))
        alembic_cfg.set_main_option("script_location", str(alembic_dir))
        # Keep the server logging setup: alembic/env.py only configures logging for the alembic CLI
        alembic_cfg.attributes["configure_logger"] = False
        sync_url = config.analytics_database_url.replace("postgresql+asyncpg://", "postgresql://")
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Database migrations completed successfully")
    except Exception as e:
        logger.warning(f"⚠️  Migration warning: {e}")
        logger.info("   Server will continue, but analytics may not work correctly")


def _run_uvicorn():
    """Run uvicorn; use import string so reload works in dev."""
    enable_reload = os.getenv("DEBUG", "false").lower() == "true"
    reload_dirs = ["mpt_mcp", "config", "alembic"] if enable_reload else None
    if enable_reload:
        logger.info(
            "🔄 Hot reload enabled - watching for .py file changes in: mpt_mcp, config, alembic"
        )
    uvicorn_log_level = "debug" if config.debug else "info"
    logger.info(f"📋 Log level: {uvicorn_log_level} (DEBUG={os.getenv('DEBUG', '(not set)')!r})")
    uvicorn.run(
        "mpt_mcp.server:app",
        host=server_host,
        port=server_port,
        log_level=uvicorn_log_level,
        proxy_headers=True,
        forwarded_allow_ips="*",
        reload=enable_reload,
        reload_dirs=reload_dirs,
        reload_includes=["*.py"],
    )


def main():
    try:
        logger.info("=" * 60)
        logger.info("🚀 SoftwareOne Marketplace MCP Server (HTTP Mode)")
        logger.info("=" * 60)
        logger.info(f"🌐 Starting server on {server_host}:{server_port}")
        logger.info("📡 Transport: Streamable HTTP (POST/DELETE)")
        logger.info("📡 Endpoint path: /mcp (registered at startup, not per-request)")
        logger.info(f"📡 Default API endpoint: {config.sse_default_base_url}")
        logger.info("🔑 Multi-tenant Authentication:")
        logger.info("   - Clients MUST provide X-MPT-Authorization header")
        logger.info("   - Optional X-MPT-Endpoint header for custom endpoints")
        logger.info(
            "   - Optional X-MPT-Validate-Fresh: true to bypass token cache (if you see 'Token invalid (cached)')"
        )
        logger.info("   - Headers are case-insensitive")
        logger.info(f"✓ Server URL: http://{server_host}:{server_port}/mcp")
        logger.info(f"✓ Health check: http://{server_host}:{server_port}/health")
        logger.info("=" * 60 + "\n")
        run_migrations()
        _run_uvicorn()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
