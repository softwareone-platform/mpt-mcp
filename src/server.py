#!/usr/bin/env python3

import asyncio
import concurrent.futures
import logging
import os
import sys
import warnings

import anyio
import uvicorn
from alembic.config import Config as AlembicConfig
from fastmcp import FastMCP
from fastmcp.resources import FunctionResource
from starlette.requests import Request
from starlette.responses import JSONResponse

from alembic import command

from .analytics import get_analytics_logger, initialize_analytics
from .config import config
from .server_context import log
from .server_docs import initialize_documentation_cache
from .server_middleware import CredentialsMiddleware
from .server_resources import register_http_resources
from .server_tools import register_http_tools

warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.*deprecated.*")
logging.getLogger("fastmcp").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

server_port = int(os.getenv("PORT", "8080"))
server_host = "0.0.0.0"
print(f"🌐 Configured for {server_host}:{server_port}", file=sys.stderr, flush=True)
# Stateless HTTP spawns a new process per request; in-memory state (e.g. docs cache) is lost.
# Force "false" so the same process serves all requests and the docs cache works.
# For serverless (e.g. Modal), set MPT_STATELESS_HTTP=true before import to allow stateless.
if os.getenv("MPT_STATELESS_HTTP", "").lower() != "true":
    os.environ["FASTMCP_STATELESS_HTTP"] = "false"
log(f"📡 FASTMCP_STATELESS_HTTP={os.getenv('FASTMCP_STATELESS_HTTP', '(unset)')} (docs cache in-process)")

mcp = FastMCP("softwareone-marketplace")
register_http_tools(mcp)
register_http_resources(mcp)


async def _create_app():
    """Build the ASGI app (init + middleware). Used so uvicorn can load via 'src.server:app' for reload."""
    await initialize_analytics(database_url=config.analytics_database_url)
    if config.analytics_enabled:
        log("📊 Analytics enabled - tracking usage metrics")
    else:
        log("📊 Analytics disabled (no database configured)")
    await initialize_documentation_cache()
    from . import server_docs

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
            log(f"📝 Registered {doc_resource_count} documentation resources for discovery")
        except Exception as e:
            log(f"⚠️  Could not register doc resources for discovery: {e}")
    else:
        log("ℹ️  Documentation resources: none (set GITBOOK_API_KEY and GITBOOK_SPACE_ID to enable). docs://{path} template is still available for reading when configured.")
    starlette_app = mcp.http_app()
    wrapped_app = CredentialsMiddleware(starlette_app)

    class HealthCheckMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                request = Request(scope, receive)
                if request.url.path in ["/", "/health"]:
                    response = JSONResponse(
                        {
                            "status": "healthy",
                            "service": "mpt-mcp-http",
                            "transport": "streamable-http",
                            "endpoint": "/mcp",
                        }
                    )
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    final_app = HealthCheckMiddleware(wrapped_app)
    print("✅ Middleware added: CredentialsMiddleware, HealthCheckMiddleware", file=sys.stderr, flush=True)

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
        log("⏩ Skipping migrations (analytics not configured)")
        return
    try:
        log("🔄 Running database migrations...")
        import pathlib

        project_root = pathlib.Path(__file__).parent.parent
        alembic_ini_path = project_root / "alembic.ini"
        alembic_dir = project_root / "alembic"
        alembic_cfg = AlembicConfig(str(alembic_ini_path))
        alembic_cfg.set_main_option("script_location", str(alembic_dir))
        sync_url = config.analytics_database_url.replace("postgresql+asyncpg://", "postgresql://")
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(alembic_cfg, "head")
        log("✅ Database migrations completed successfully")
    except Exception as e:
        log(f"⚠️  Migration warning: {e}")
        log("   Server will continue, but analytics may not work correctly")


def _run_uvicorn():
    """Run uvicorn; use import string so reload works in dev."""
    enable_reload = os.getenv("DEBUG", "false").lower() == "true"
    reload_dirs = ["src", "config", "alembic"] if enable_reload else None
    if enable_reload:
        print("🔄 Hot reload enabled - watching for .py file changes in: src, config, alembic", file=sys.stderr, flush=True)
    uvicorn_log_level = "debug" if config.debug else "info"
    print(
        f"📋 Log level: {uvicorn_log_level} (DEBUG={os.getenv('DEBUG', '(not set)')!r})",
        file=sys.stderr,
        flush=True,
    )
    uvicorn.run(
        "src.server:app",
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
    def log_startup(message):
        print(message, file=sys.stderr, flush=True)

    try:
        log_startup("=" * 60)
        log_startup("🚀 SoftwareOne Marketplace MCP Server (HTTP Mode)")
        log_startup("=" * 60)
        log_startup(f"\n🌐 Starting server on {server_host}:{server_port}")
        log_startup("📡 Transport: Streamable HTTP (POST/DELETE)")
        log_startup("📡 Endpoint path: /mcp")
        log_startup(f"📡 Default API endpoint: {config.sse_default_base_url}")
        log_startup("\n🔑 Multi-tenant Authentication:")
        log_startup("   - Clients MUST provide X-MPT-Authorization header")
        log_startup("   - Optional X-MPT-Endpoint header for custom endpoints")
        log_startup("   - Optional X-MPT-Validate-Fresh: true to bypass token cache (if you see 'Token invalid (cached)')")
        log_startup("   - Headers are case-insensitive")
        log_startup(f"\n✓ Server URL: http://{server_host}:{server_port}/mcp")
        log_startup(f"✓ Health check: http://{server_host}:{server_port}/health")
        log_startup("=" * 60 + "\n")
        run_migrations()
        _run_uvicorn()
    except KeyboardInterrupt:
        log_startup("\n\nShutting down server...")
        analytics = get_analytics_logger()
        if analytics:
            log_startup("📊 Flushing pending analytics events...")
            anyio.run(analytics.cleanup)
        sys.exit(0)
    except Exception as e:
        log_startup(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        analytics = get_analytics_logger()
        if analytics:
            anyio.run(analytics.cleanup)
        sys.exit(1)


if __name__ == "__main__":
    main()
