import logging
import os
import sys

import uvicorn

from mpt_mcp.config import config
from mpt_mcp.runtime.logging import configure_logging
from mpt_mcp.runtime.migrations import run_migrations

logger = logging.getLogger(__name__)

APP_IMPORT_PATH = "mpt_mcp.runtime.main:app"
# Listen on every interface: the server runs in a container (Cloud Run)
SERVER_HOST = "0.0.0.0"  # ruff: ignore[hardcoded-bind-all-interfaces]
DEFAULT_PORT = "8080"
RELOAD_DIRS = ("mpt_mcp", "config", "alembic")


def run_uvicorn(port: int) -> None:
    """Run uvicorn with the app import path, so DEBUG=true reloads it on code changes."""
    enable_reload = config.debug
    if enable_reload:
        logger.info(
            "Hot reload enabled - watching for .py file changes in: %s", ", ".join(RELOAD_DIRS)
        )
    uvicorn_log_level = "debug" if config.debug else "info"
    logger.info("Log level: %s (DEBUG=%r)", uvicorn_log_level, os.getenv("DEBUG", "(not set)"))
    uvicorn.run(
        APP_IMPORT_PATH,
        host=SERVER_HOST,
        port=port,
        log_level=uvicorn_log_level,
        proxy_headers=True,
        forwarded_allow_ips="*",
        reload=enable_reload,
        reload_dirs=list(RELOAD_DIRS) if enable_reload else None,
        reload_includes=["*.py"] if enable_reload else None,
    )


def log_startup(port: int) -> None:
    """Log where the server listens and the headers clients must send."""
    logger.info("=" * 60)
    logger.info("SoftwareOne Marketplace MCP Server (HTTP Mode)")
    logger.info("=" * 60)
    logger.info("Starting server on %s:%s", SERVER_HOST, port)
    logger.info("Transport: Streamable HTTP (POST/DELETE)")
    logger.info("Endpoint path: /mcp (registered at startup, not per-request)")
    logger.info("Default API endpoint: %s", config.http_default_base_url)
    logger.info("Multi-tenant Authentication:")
    logger.info("- Clients MUST provide X-MPT-Authorization header")
    logger.info("- Optional X-MPT-Endpoint header for custom endpoints")
    logger.info(
        "- Optional X-MPT-Validate-Fresh: true to bypass token cache (if you see 'Token "
        "invalid (cached)')"
    )
    logger.info("- Headers are case-insensitive")
    logger.info("Server URL: http://%s:%s/mcp", SERVER_HOST, port)
    logger.info("Health check: http://%s:%s/health", SERVER_HOST, port)
    logger.info("=" * 60)


def main() -> None:
    """Run the HTTP server: log the startup banner, apply migrations and start uvicorn."""
    configure_logging(logging.DEBUG if config.debug else logging.INFO)
    port = int(os.getenv("PORT", DEFAULT_PORT))
    try:
        log_startup(port)
        run_migrations()
        run_uvicorn(port)
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        sys.exit(0)
    except Exception:
        logger.exception("Server error")
        sys.exit(1)


if __name__ == "__main__":
    main()
