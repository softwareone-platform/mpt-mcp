#!/usr/bin/env python3
"""
MCP Server for SoftwareOne Marketplace API - HTTP Streamable Transport

Main remote access server using HTTP Streamable transport (POST/DELETE /mcp endpoint).
Works with Cursor, Antigravity IDE, and other MCP clients supporting HTTP transport.

Features:
- Multi-tenant architecture: ALWAYS requires client credentials
- Client credentials via HTTP headers (X-MPT-Authorization, X-MPT-Endpoint)
- Automatic user identification from token (idt:TKN-XXXX-XXXX format)
- Bearer token resilience (works with or without Bearer prefix)
- URL normalization (handles any base URL format)
- Cloud-ready (Google Cloud Run, etc.)

This HTTP server is designed for multi-tenant cloud deployments where each
client provides their own API credentials. No server-side credentials needed!
"""

import logging
import os
import sys
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

import anyio
import uvicorn
from alembic.config import Config as AlembicConfig
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from alembic import command

# Suppress noisy MCP library logs
logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

from . import endpoint_registry
from .analytics import get_analytics_logger, initialize_analytics
from .api_client import APIClient
from .config import config
from .documentation_cache import DocumentationCache
from .gitbook_client import GitBookClient
from .mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_quick_queries,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
)
from .token_validator import normalize_token

# ============================================================================
# Context Variables for request-scoped data (like SSE server)
# ============================================================================

# Context variables for structured logging and credential passing
_current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)
_current_endpoint: ContextVar[str | None] = ContextVar("current_endpoint", default=None)
_current_validate_fresh: ContextVar[bool] = ContextVar("current_validate_fresh", default=False)


def log(message: str, **kwargs):
    """Contextual logging with session and user info."""
    session_id = _current_session_id.get()
    user_id = _current_user_id.get()

    context_parts = []
    if session_id:
        context_parts.append(f"sess:{session_id[:8]}")
    if user_id:
        context_parts.append(f"user:{user_id}")

    prefix = f"[{('|'.join(context_parts))}] " if context_parts else ""
    print(f"{prefix}{message}", file=sys.stderr, flush=True, **kwargs)


# ============================================================================
# Middleware to extract credentials from HTTP headers
# ============================================================================

# Rate limiter for request logs (avoid spamming logs with subscribe requests)
_last_log_time: dict[str, datetime] = defaultdict(lambda: datetime.min)
_log_cooldown = timedelta(seconds=30)  # Only log once per 30 seconds per user


class CredentialsMiddleware:
    """
    ASGI middleware that extracts credentials from HTTP headers and stores
    them in ContextVars, making them available to tool functions.

    Also validates tokens for capability discovery operations (list tools/resources)
    to provide early feedback on invalid credentials.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)

            # Extract credentials from headers (case-insensitive)
            auth_header_raw = request.headers.get("x-mpt-authorization") or request.headers.get("X-MPT-Authorization")
            # Normalize token: strip whitespace and strip leading "Bearer " so cache key and API calls are consistent
            auth_header = normalize_token(auth_header_raw) if auth_header_raw else auth_header_raw
            endpoint_header = request.headers.get("x-mpt-endpoint") or request.headers.get("X-MPT-Endpoint")
            # Optional: force re-validation (bypass cache) to recover from stale "Token invalid (cached)"
            validate_fresh = (request.headers.get("x-mpt-validate-fresh") or request.headers.get("X-MPT-Validate-Fresh") or "").strip().lower() in ("1", "true", "yes")

            # Extract user ID from token for logging
            user_id = None
            if auth_header:
                user_id = APIClient._extract_user_id(auth_header)

            # Extract session ID from query params or generate one
            session_id = request.query_params.get("session_id")

            # Extract client info from User-Agent for analytics
            user_agent = request.headers.get("user-agent", "")
            client_info = None
            if "cursor" in user_agent.lower():
                client_info = "Cursor"
            elif "claude" in user_agent.lower():
                client_info = "Claude Desktop"
            elif user_agent:
                client_info = user_agent.split("/")[0][:50]  # First part, max 50 chars

            # Extract client IP address (works with Cloud Run and other proxies)
            # Cloud Run sets X-Forwarded-For with the real client IP
            client_ip = None
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                # X-Forwarded-For can be a comma-separated list: "client, proxy1, proxy2"
                # Take the first one (original client)
                client_ip = forwarded_for.split(",")[0].strip()
            else:
                # Fallback to X-Real-IP (some proxies use this)
                client_ip = request.headers.get("x-real-ip")
                if not client_ip:
                    # Last resort: use direct client host (may be proxy IP)
                    if request.client:
                        client_ip = request.client.host

            # Set context variables for this request
            token_ctx = user_ctx = session_ctx = endpoint_ctx = None

            if auth_header:
                token_ctx = _current_token.set(auth_header)
            if endpoint_header:
                endpoint_ctx = _current_endpoint.set(endpoint_header)
            if validate_fresh:
                _ = _current_validate_fresh.set(True)
            if user_id:
                user_ctx = _current_user_id.set(user_id)
            if session_id:
                session_ctx = _current_session_id.set(session_id)

            # Set analytics context
            analytics = get_analytics_logger()
            if analytics and config.analytics_enabled:
                analytics.set_context(
                    token=auth_header or "",
                    endpoint=endpoint_header or config.sse_default_base_url,
                    client_info=client_info,
                    client_ip=client_ip,
                )

            try:
                # Log meaningful requests only (skip GET which are just SSE checks)
                # Use rate limiting to avoid log spam from subscribe requests
                if request.url.path == "/mcp" and request.method == "POST":
                    log_key = f"{user_id or 'anonymous'}@{endpoint_header or config.sse_default_base_url}"
                    now = datetime.now()

                    # Only log if cooldown period has passed
                    if now - _last_log_time[log_key] >= _log_cooldown:
                        endpoint_display = endpoint_header or config.sse_default_base_url
                        # Shorten endpoint URL for cleaner logs
                        if endpoint_display.startswith("https://"):
                            endpoint_display = endpoint_display.replace("https://", "").split("/")[0]
                        token_status = "✓" if auth_header else "✗"
                        log(f"📨 {user_id or 'anonymous'} @ {endpoint_display} [{token_status}] (active)")
                        _last_log_time[log_key] = now

                # Note: We validate tokens on first tool call, not during capability discovery
                # This avoids ASGI body reconstruction issues while still being secure
                # Invalid tokens will fail when they try to actually use the tools

                # Pass request through to FastMCP app
                await self.app(scope, receive, send)
            finally:
                # Reset context variables
                if token_ctx is not None:
                    _current_token.reset(token_ctx)
                if endpoint_ctx is not None:
                    _current_endpoint.reset(endpoint_ctx)
                if user_ctx is not None:
                    _current_user_id.reset(user_ctx)
                if session_ctx is not None:
                    _current_session_id.reset(session_ctx)
        else:
            await self.app(scope, receive, send)


# ============================================================================
# FastMCP Server Setup
# ============================================================================

# Configure transport security for public API server
transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False, allowed_hosts=["*"], allowed_origins=["*"])

# Get port from environment (Cloud Run sets PORT)
server_port = int(os.getenv("PORT", "8080"))
server_host = "0.0.0.0"  # Bind to all interfaces for Cloud Run

print("✅ Transport security configured for public API", file=sys.stderr, flush=True)
print(f"🌐 Configured for {server_host}:{server_port}", file=sys.stderr, flush=True)

# Initialize FastMCP server with stateless HTTP mode
# Stateless mode treats each request independently (no session required)
# This is the primary remote access mode for Cursor, Antigravity, etc.
mcp = FastMCP(
    "softwareone-marketplace",
    transport_security=transport_security,
    host=server_host,
    port=server_port,
    stateless_http=True,  # Each request is independent
)

# Global documentation cache
documentation_cache: DocumentationCache | None = None
_docs_cache_initialized: bool = False


async def initialize_documentation_cache():
    """Initialize the documentation cache from GitBook and register resources"""
    global documentation_cache, _docs_cache_initialized

    if _docs_cache_initialized:
        return

    # Only initialize if GitBook credentials are provided
    if config.gitbook_api_key and config.gitbook_space_id:
        try:
            gitbook_client = GitBookClient(
                api_key=config.gitbook_api_key,
                space_id=config.gitbook_space_id,
                base_url=config.gitbook_api_base_url,
                max_concurrent_requests=config.gitbook_max_concurrent_requests,
            )

            # Validate credentials
            if await gitbook_client.validate_credentials():
                documentation_cache = DocumentationCache(
                    gitbook_client=gitbook_client,
                    refresh_interval_hours=config.gitbook_cache_refresh_hours,
                    public_url=config.gitbook_public_url,
                )

                # Initial cache load
                await documentation_cache.refresh()

                # Register all documentation pages as static resources
                doc_resources = await documentation_cache.list_resources()
                log(f"📝 Registering {len(doc_resources)} documentation pages as MCP resources...")

                for doc_data in doc_resources:
                    doc_resource = DocResource(
                        uri=doc_data["uri"],
                        name=doc_data["name"],
                        description=doc_data.get("description", ""),
                        mime_type=doc_data.get("mimeType", "text/markdown"),
                    )
                    mcp._resource_manager.add_resource(doc_resource)

                log(f"✅ Registered {len(doc_resources)} documentation resources")
                log("✓ Documentation cache initialized")
            else:
                log("⚠️  GitBook credentials invalid, documentation cache disabled")
                documentation_cache = DocumentationCache(gitbook_client=None)
        except Exception as e:
            log(f"⚠️  Failed to initialize documentation cache: {e}")
            documentation_cache = DocumentationCache(gitbook_client=None)
    else:
        log("ℹ️  GitBook not configured, documentation cache disabled")
        documentation_cache = DocumentationCache(gitbook_client=None)

    _docs_cache_initialized = True


# Create a simple Resource class for static documentation resources
from mcp.server.fastmcp.resources import Resource


class DocResource(Resource):
    """Static documentation resource"""

    async def read(self) -> str:
        """Read the resource content from the documentation cache"""
        if documentation_cache and documentation_cache.is_enabled:
            content = await documentation_cache.get_resource(str(self.uri))
            return content if content else ""
        return ""


# ============================================================================
# Resource Discovery
# ============================================================================
# Note: We use MCP Resources for documentation (static, ~913 pages)
# API endpoint discovery is handled via marketplace_resources() tool
# This is simpler and works better with MCP's architecture
# ============================================================================


def normalize_endpoint_url(endpoint: str) -> str:
    """Normalize the API endpoint URL by removing trailing paths like /public"""
    if not endpoint:
        return endpoint

    endpoint = endpoint.rstrip("/")

    if endpoint.endswith("/public"):
        endpoint = endpoint[:-7]

    return endpoint


def get_current_credentials() -> tuple[str | None, str]:
    """Get credentials from the current request context (set by middleware)."""
    token = _current_token.get()
    endpoint = _current_endpoint.get() or config.sse_default_base_url
    return token, normalize_endpoint_url(endpoint)


async def get_client_api_client_http(validate_token: bool = True) -> APIClient:
    """
    Get an API client using credentials from the current request context.

    Args:
        validate_token: Whether to validate the token against the API (default: True)

    Returns:
        APIClient instance

    Raises:
        ValueError: If credentials are missing or token validation fails
    """
    token, endpoint = get_current_credentials()

    if not token:
        raise ValueError("Missing X-MPT-Authorization header. Please provide your API token in the X-MPT-Authorization header.")

    # Validate token before creating API client
    if validate_token:
        from .token_validator import validate_token

        use_cache = not _current_validate_fresh.get()
        is_valid, token_info, error = await validate_token(token, endpoint, use_cache=use_cache)

        if not is_valid:
            log(f"❌ Token validation failed: {error}")
            raise ValueError(f"Token validation failed: {error}. Please ensure your API token is valid and active.")

        # Log account information on successful validation
        if token_info:
            account_name = token_info.get("account", {}).get("name", "Unknown")
            account_id = token_info.get("account", {}).get("id", "Unknown")
            log(f"✅ Token validated for {endpoint} - Account: {account_name} ({account_id})")
        else:
            log(f"✅ Token validated for {endpoint}")

    return APIClient(base_url=endpoint, token=token)


# ============================================================================
# MCP Tools - Same as SSE server but using ContextVar credentials
# ============================================================================


@mcp.tool()
async def marketplace_query(
    resource: str,
    rql: str = "",
    limit: int | None = None,
    offset: int | None = None,
    page: int | None = None,
    select: str | None = None,
    order: str | None = None,
    path_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    marketplace_query(resource, rql, limit, offset, select, order): Query the SoftwareOne Marketplace API.

    Query the SoftwareOne Marketplace API using Resource Query Language (RQL).

    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string for complex filtering and sorting. Examples: eq(status,Active), and(eq(status,Active),gt(price,100)), ilike(name,*Microsoft*). Dates use UTC format YYYY-MM-DDTHH:MM:SS.mmmZ (e.g. 2026-01-31T23:00:00.000Z). Note: Pagination and selection use key=value syntax like limit=100, select=+status, order=-created
        limit: Maximum number of items to return (e.g., 10, 50, 100). Defaults to 10 if not specified. Maximum allowed is 100 (values above 100 are capped to 100). When using limit up to 100, use select= with only the fields you need (from marketplace_resource_schema) to avoid huge responses.
        offset: Number of items to skip for pagination (e.g., 0, 20, 40)
        page: Page number (alternative to offset)
        select: Fields to include/exclude (e.g., +name,+description or -metadata). IMPORTANT: When filtering or sorting by audit fields (e.g., audit.created.at), you must include 'audit' in select. Dates in RQL use UTC: YYYY-MM-DDTHH:MM:SS.mmmZ (e.g. 2026-01-31T23:00:00.000Z). The server will auto-add this if detected. For nested collections: +subscriptions returns the full nested representation (each item as a full object); +subscriptions.id returns only the ids of the nested collection; +subscriptions.id,+subscriptions.name returns only id and name per nested item. Prefer +subscriptions.id,+subscriptions.name when you only need to count or show id/name. RQL filter fields must exist on the resource—use marketplace_resource_schema(resource) to check (e.g. subscriptionsCount does not exist).
        order: Sort order (e.g., -created for descending, +name for ascending). When using audit fields (e.g., -audit.created.at), ensure select includes 'audit'.
        path_params: Path parameters for resources requiring IDs (e.g., {id: PRD-1234-5678} for catalog.products.by_id, {orderId: ORD-1234-5678} for commerce.orders.{orderId}.lines)

    Returns:
        API response with data and pagination information

    Use marketplace_resources() to see all available resources.
    """
    # Get credentials from request context (set by middleware)
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}

    # Get endpoints registry for this client's API endpoint
    api_base_url = api_client.base_url
    log(f"🔍 Using API endpoint: {api_base_url}")

    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {
            "error": "Failed to load OpenAPI spec for your endpoint",
            "api_endpoint": api_base_url,
            "details": str(e),
            "hint": f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
        }

    # Use shared implementation; log_fn=log so Query/Path/Params/Result count show in docker logs (stderr)
    return await execute_marketplace_query(
        resource=resource,
        rql=rql,
        limit=limit,
        offset=offset,
        page=page,
        select=select,
        order=order,
        path_params=path_params,
        api_client=api_client,
        endpoints_registry=endpoints_registry_data,
        log_fn=log,
        analytics_logger=get_analytics_logger(),
        config=config,
    )


@mcp.tool()
async def marketplace_quick_queries() -> dict[str, Any]:
    """
    Get pre-built query templates for common use cases.

    Returns ready-to-use query examples organized by category. These templates
    help you quickly perform common tasks without learning RQL syntax.

    Returns:
        Dictionary of query templates organized by category

    Example: marketplace_quick_queries() shows templates for finding recent
    orders, active products, specific vendors, etc.
    """
    return execute_marketplace_quick_queries()


@mcp.tool()
async def marketplace_resources() -> dict[str, Any]:
    """
    marketplace_resources(): List all available API resources.

    Returns a categorized list of all available API endpoints including resource paths and summaries, common filterable fields (when available), example queries per resource, and response structure hints.

    Returns:
        Detailed resource catalog organized by category

    Example: marketplace_resources() shows all available resources like catalog.products, commerce.orders, etc. with filtering hints and example queries for each.
    """
    # Get credentials from request context
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}

    # Get endpoints registry for this client's API endpoint
    api_base_url = api_client.base_url

    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {"error": "Failed to load OpenAPI spec", "details": str(e)}

    # Use shared implementation
    user_id = _current_user_id.get()
    return await execute_marketplace_resources(
        api_base_url=api_base_url,
        user_id=user_id,
        endpoints_registry=endpoints_registry_data,
    )


@mcp.tool()
async def marketplace_resource_info(resource: str) -> dict[str, Any]:
    """
    marketplace_resource_info(resource): Get detailed information about a specific resource.

    Args:
        resource: The resource to get information about (e.g., catalog.products)

    Returns:
        Detailed resource information including path, parameters, and response schema
    """
    # Get credentials from request context
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}

    # Get endpoints registry for this client's API endpoint
    api_base_url = api_client.base_url

    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {"error": "Failed to load OpenAPI spec", "details": str(e)}

    # Use shared implementation
    return await execute_marketplace_resource_info(
        resource=resource,
        endpoints_registry=endpoints_registry_data,
    )


@mcp.tool()
async def marketplace_resource_schema(resource: str) -> dict[str, Any]:
    """
    marketplace_resource_schema(resource): Get the full schema for a resource.

    This returns the detailed schema including all fields, types, nested structures, and descriptions. Useful for understanding what fields are available for filtering and what the response structure will be.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)

    Returns:
        Complete JSON schema with field types, descriptions, enums, and examples

    Example: marketplace_resource_schema(resource=catalog.products) returns full schema showing all product fields like id, name, status, vendor, etc.
    """
    # Get credentials from request context
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}

    # Get the OpenAPI spec and endpoints registry
    api_base_url = api_client.base_url

    try:
        spec = await endpoint_registry.get_openapi_spec(api_base_url)
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {"error": "Failed to load OpenAPI spec", "details": str(e)}

    # Use shared implementation
    return await execute_marketplace_resource_schema(
        resource=resource,
        openapi_spec=spec,
        endpoints_registry=endpoints_registry_data,
    )


# ============================================================================
# Server Startup with Middleware
# ============================================================================


def run_migrations():
    """
    Run Alembic database migrations on startup.

    This ensures the database schema is up-to-date before the server starts.
    Safe to run multiple times - Alembic will skip already-applied migrations.
    """
    if not config.analytics_database_url:
        log("⏩ Skipping migrations (analytics not configured)")
        return

    try:
        log("🔄 Running database migrations...")

        # Get the project root directory (where alembic.ini is located)
        import pathlib

        project_root = pathlib.Path(__file__).parent.parent
        alembic_ini_path = project_root / "alembic.ini"
        alembic_dir = project_root / "alembic"

        # Configure Alembic programmatically
        alembic_cfg = AlembicConfig(str(alembic_ini_path))
        alembic_cfg.set_main_option("script_location", str(alembic_dir))

        # Convert async URL to sync URL for Alembic (psycopg2 instead of asyncpg)
        sync_url = config.analytics_database_url.replace("postgresql+asyncpg://", "postgresql://")
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

        # Run migrations to head
        command.upgrade(alembic_cfg, "head")

        log("✅ Database migrations completed successfully")
    except Exception as e:
        log(f"⚠️  Migration warning: {e}")
        log("   Server will continue, but analytics may not work correctly")
        # Don't fail server startup if migrations fail


async def run_server_async():
    """Run the HTTP server with middleware for credential extraction."""

    # Initialize analytics (if configured)
    await initialize_analytics(database_url=config.analytics_database_url)
    if config.analytics_enabled:
        log("📊 Analytics enabled - tracking usage metrics")
    else:
        log("📊 Analytics disabled (no database configured)")

    # Initialize documentation cache on startup
    await initialize_documentation_cache()

    # Get the Starlette app from FastMCP
    starlette_app = mcp.streamable_http_app()

    # Wrap with our credentials middleware
    wrapped_app = CredentialsMiddleware(starlette_app)

    # Add health check endpoint by wrapping again
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

    # Configure custom access log filter to reduce noise
    class AccessLogFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            # Suppress /mcp and /health access logs (we have custom logging for /mcp)
            if hasattr(record, "args") and len(record.args) >= 3:
                path = str(record.args[2])  # Path is typically the 3rd arg
                if path in ["/mcp", "/health", "GET /health", "POST /mcp"]:
                    return False
            return True

    # Apply filter to uvicorn access logger
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(AccessLogFilter())

    # Run with uvicorn
    # Enable reload in development mode (when DEBUG env var is set)
    enable_reload = os.getenv("DEBUG", "false").lower() == "true"

    # Watch all directories that contain Python files for hot reload
    reload_dirs = None
    if enable_reload:
        # Monitor all mounted directories that contain Python code
        reload_dirs = [
            "/app/src",  # Main source code
            "/app/config",  # Configuration files
            "/app/alembic",  # Database migrations
        ]
        print("🔄 Hot reload enabled - watching for .py file changes in:", file=sys.stderr, flush=True)
        for dir_path in reload_dirs:
            print(f"   - {dir_path}", file=sys.stderr, flush=True)

    uvicorn_config = uvicorn.Config(
        final_app,
        host=server_host,
        port=server_port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
        reload=enable_reload,  # Enable hot reload in development
        reload_dirs=reload_dirs,  # Watch all Python directories for changes
        reload_includes=["*.py"],  # Only watch Python files
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


# ============================================================================
# MCP Resources - Documentation from GitBook
# ============================================================================


@mcp.tool()
async def marketplace_docs_index() -> dict[str, Any]:
    """
    marketplace_docs_index(): Get the documentation index.

    Returns a hierarchical view of all documentation sections and subsections
    with page counts, helping you understand what documentation is available
    without listing all 900+ individual pages.

    Returns:
        Dictionary containing:
        - total_pages: Total number of documentation pages
        - sections: List of sections with subsections and page counts

    Example:
        >>> index = marketplace_docs_index()
        >>> print(f"Total pages: {index['total_pages']}")
        >>> for section in index["sections"]:
        ...     print(f"{section['name']}: {section['total_pages']} pages")
    """
    analytics = get_analytics_logger()
    import time

    start_time = time.time()
    try:
        await initialize_documentation_cache()

        if not documentation_cache or not documentation_cache.is_enabled:
            result = {
                "total_pages": 0,
                "sections": [],
                "error": "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID.",
            }
            if analytics and config.analytics_enabled:
                await analytics.log_tool_call(
                    tool_name="marketplace_docs_index", response_time_ms=int((time.time() - start_time) * 1000), success=False, error_message="Not initialized"
                )
            return result

        result = await documentation_cache.get_documentation_index()
        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(
                tool_name="marketplace_docs_index", response_time_ms=int((time.time() - start_time) * 1000), success=True, result_count=result.get("total_pages", 0)
            )
        return result
    except Exception as e:
        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(tool_name="marketplace_docs_index", response_time_ms=int((time.time() - start_time) * 1000), success=False, error_message=str(e))
        raise


@mcp.tool()
async def marketplace_docs_list(section: str = None, subsection: str = None, search: str = None, limit: int = 100) -> dict[str, Any]:
    """
    marketplace_docs_list(search): List documentation pages (optionally filtered by keyword).

    Use this to discover relevant documentation pages by filtering by section,
    subsection, or searching by keyword. Returns up to 100 results by default.

    Args:
        section: Filter by top-level section (e.g., "developer-resources", "help-and-support")
        subsection: Filter by subsection (e.g., "rest-api", "billing")
        search: Search keyword in page titles and paths (case-insensitive)
        limit: Maximum number of results to return (default: 100)

    Returns:
        Dictionary containing:
        - total: Number of matching documentation pages
        - resources: List of matching documentation resources with URI, name, and description
        - filters_applied: Summary of filters used
        - tip: Suggestion for narrowing results if needed

    Examples:
        >>> # Get all billing documentation
        >>> result = marketplace_docs_list(search="billing")

        >>> # Get API reference pages
        >>> result = marketplace_docs_list(section="developer-resources", subsection="rest-api", limit=50)

        >>> # Search for invoice-related docs
        >>> result = marketplace_docs_list(search="invoice")
    """
    analytics = get_analytics_logger()
    import time

    start_time = time.time()
    try:
        await initialize_documentation_cache()

        if not documentation_cache or not documentation_cache.is_enabled:
            result = {
                "total": 0,
                "resources": [],
                "error": "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID.",
            }
            if analytics and config.analytics_enabled:
                await analytics.log_tool_call(
                    tool_name="marketplace_docs_list", response_time_ms=int((time.time() - start_time) * 1000), success=False, error_message="Not initialized"
                )
            return result

        resources = await documentation_cache.list_resources(section=section, subsection=subsection, search=search, limit=limit)

        # Expose browser_url at top level when present (for agent to show public link to user)
        resources_for_response = []
        for r in resources:
            item = dict(r)
            if r.get("metadata", {}).get("browser_url"):
                item["browser_url"] = r["metadata"]["browser_url"]
            resources_for_response.append(item)

        # Build filter summary
        filters = []
        if section:
            filters.append(f"section={section}")
        if subsection:
            filters.append(f"subsection={subsection}")
        if search:
            filters.append(f"search='{search}'")

        result = {
            "total": len(resources_for_response),
            "resources": resources_for_response,
            "filters_applied": ", ".join(filters) if filters else "none",
            "usage": "Use marketplace_docs_read(uri='docs://path') to read a specific page. Prefer showing users the browser_url (public link) when present; do not show internal uri or id to end users.",
        }

        # Add tip if results are large
        if len(resources) >= limit:
            result["tip"] = f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
        elif len(resources) > 50:
            result["tip"] = "Consider using 'section' or 'subsection' filters to narrow down results."

        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(
                tool_name="marketplace_docs_list", response_time_ms=int((time.time() - start_time) * 1000), success=True, result_count=result.get("total", 0)
            )
        return result
    except Exception as e:
        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(tool_name="marketplace_docs_list", response_time_ms=int((time.time() - start_time) * 1000), success=False, error_message=str(e))
        raise


@mcp.tool()
async def marketplace_docs_read(uri: str) -> str:
    """
    marketplace_docs_read(uri): Read documentation content.

    Read documentation content for a specific URI from the SoftwareOne Marketplace Platform documentation.

    Args:
        uri: Documentation URI (e.g., "docs://getting-started/authentication" or "docs://api-reference/orders")

    Returns:
        Documentation content as markdown text

    Example:
        >>> content = marketplace_docs_read(uri="docs://getting-started")
        >>> print(content)
    """
    analytics = get_analytics_logger()
    import time

    start_time = time.time()
    try:
        await initialize_documentation_cache()

        if not documentation_cache or not documentation_cache.is_enabled:
            result = "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
            if analytics and config.analytics_enabled:
                await analytics.log_resource_read(
                    resource_uri=uri, success=False, response_time_ms=int((time.time() - start_time) * 1000), error_message="Documentation cache not available"
                )
            return result

        content = await documentation_cache.get_resource(uri)

        if content is None:
            result = f"Documentation page not found: {uri}\n\nUse marketplace_docs_list() to see available pages."
            if analytics and config.analytics_enabled:
                await analytics.log_resource_read(
                    resource_uri=uri, success=False, response_time_ms=int((time.time() - start_time) * 1000), error_message="Documentation page not found"
                )
            return result

        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(resource_uri=uri, success=True, response_time_ms=int((time.time() - start_time) * 1000), cache_hit=True)
        return content
    except Exception as e:
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(resource_uri=uri, success=False, response_time_ms=int((time.time() - start_time) * 1000), error_message=str(e))
        raise


@mcp.tool()
async def marketplace_resources_info() -> dict[str, Any]:
    """
    Get information about available resources (documentation + API)

    Returns statistics about:
    - Documentation resources (cached from GitBook)
    - API resources (cached per endpoint from OpenAPI specs)
    - Token validation cache statistics

    This helps understand what resources are available and how caching works.

    Returns:
        Dictionary with resource statistics and cache information
    """
    analytics = get_analytics_logger()
    import time

    start_time = time.time()
    try:
        result = {
            "documentation": {"enabled": False, "total_pages": 0, "cache_info": None},
            "token_validation": {"enabled": False, "cache_stats": None},
        }

        # Documentation resources info
        if documentation_cache and documentation_cache.is_enabled:
            cache_info = documentation_cache.get_cache_info()
            result["documentation"] = {
                "enabled": True,
                "total_pages": cache_info.get("resource_count", 0),
                "cache_info": cache_info,
            }

        # Token validation info
        try:
            from .token_validator import get_token_cache

            token_cache = get_token_cache()
            result["token_validation"] = {
                "enabled": True,
                "cache_stats": token_cache.get_stats(),
                "description": "Token validation cache prevents repeated API calls for authentication",
            }
        except Exception as e_inner:
            result["token_validation"] = {"enabled": False, "error": str(e_inner)}

        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(tool_name="marketplace_resources_info", response_time_ms=int((time.time() - start_time) * 1000), success=True)
        return result
    except Exception as e:
        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(tool_name="marketplace_resources_info", response_time_ms=int((time.time() - start_time) * 1000), success=False, error_message=str(e))
        raise


# ============================================================================
# MCP Resources - URI Handlers
# ============================================================================


@mcp.resource("api://openapi.json")
async def get_openapi_spec() -> str:
    """
    Get the OpenAPI specification for the current user's API endpoint.

    Returns the full OpenAPI 3.0 specification as JSON, including all available
    endpoints, schemas, parameters, and response formats for the API environment
    the user is connected to (e.g., production, staging, dev).

    This allows AI agents to understand the complete API structure and capabilities
    without making multiple queries.

    Returns:
        JSON string containing the full OpenAPI 3.0 specification

    Example:
        The OpenAPI spec includes:
        - All 300+ API endpoints with their paths and methods
        - Request/response schemas
        - Parameter definitions
        - Authentication requirements
        - Data models and types
    """
    import json
    import time

    from .endpoint_registry import _openapi_specs, get_openapi_spec

    analytics = get_analytics_logger()
    start_time = time.time()
    uri = "api://openapi.json"

    # Get current user credentials from context
    token, endpoint = get_current_credentials()

    if not token:
        error_response = json.dumps(
            {
                "error": "Authentication required",
                "message": "Please provide X-MPT-Authorization header to access OpenAPI specification",
                "hint": "The OpenAPI spec is specific to your API endpoint and requires authentication",
            },
            indent=2,
        )
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=False,
                response_time_ms=int((time.time() - start_time) * 1000),
                error_message="Authentication required",
            )
        return error_response

    # Validate token
    from .token_validator import validate_token

    is_valid, token_info, error = await validate_token(token, endpoint)

    if not is_valid:
        error_response = json.dumps(
            {
                "error": "Invalid credentials",
                "message": f"Token validation failed: {error}",
                "hint": "Please check your X-MPT-Authorization header",
            },
            indent=2,
        )
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=False,
                response_time_ms=int((time.time() - start_time) * 1000),
                error_message=f"Invalid credentials: {error}",
            )
        return error_response

    # Get OpenAPI spec for the user's endpoint
    try:
        # Check if spec is already cached (cache hit detection)
        cache_hit = endpoint in _openapi_specs

        openapi_spec = await get_openapi_spec(endpoint, force_refresh=False)

        if not openapi_spec:
            error_response = json.dumps(
                {
                    "error": "OpenAPI specification not available",
                    "message": f"Could not load OpenAPI spec for endpoint: {endpoint}",
                    "hint": "The API endpoint may be unreachable or the specification is not available",
                },
                indent=2,
            )
            if analytics and config.analytics_enabled:
                await analytics.log_resource_read(
                    resource_uri=uri,
                    success=False,
                    response_time_ms=int((time.time() - start_time) * 1000),
                    error_message="OpenAPI specification not available",
                )
            return error_response

        # Add metadata about the spec
        spec_with_metadata = {
            "api_endpoint": endpoint,
            "authenticated_as": token_info.get("account", {}).get("name", "Unknown") if token_info else "Unknown",
            "account_id": token_info.get("account", {}).get("id", "Unknown") if token_info else "Unknown",
            "openapi_version": openapi_spec.get("openapi", "3.0"),
            "info": openapi_spec.get("info", {}),
            "spec": openapi_spec,
        }

        # Log successful resource read
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=True,
                response_time_ms=int((time.time() - start_time) * 1000),
                cache_hit=cache_hit,
            )

        # Return the full OpenAPI spec as formatted JSON
        return json.dumps(spec_with_metadata, indent=2)

    except Exception as e:
        error_response = json.dumps({"error": "Failed to fetch OpenAPI specification", "message": str(e), "endpoint": endpoint}, indent=2)
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=False,
                response_time_ms=int((time.time() - start_time) * 1000),
                error_message=str(e),
            )
        return error_response


@mcp.resource("docs://{path}")
async def get_documentation_resource(path: str) -> str:
    """
    Get documentation content from documentation cache

    Args:
        path: Resource path (e.g., "getting-started/authentication")

    Returns:
        Documentation content as markdown
    """
    import time

    analytics = get_analytics_logger()
    start_time = time.time()
    uri = f"docs://{path}"

    try:
        await initialize_documentation_cache()

        if not documentation_cache or not documentation_cache.is_enabled:
            error_msg = "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
            if analytics and config.analytics_enabled:
                await analytics.log_resource_read(
                    resource_uri=uri,
                    success=False,
                    response_time_ms=int((time.time() - start_time) * 1000),
                    error_message=error_msg,
                )
            return error_msg

        # Check if content is already cached (cache hit detection)
        cache_hit = False
        if uri in documentation_cache._resources:
            resource = documentation_cache._resources[uri]
            if resource.get("content") is not None:
                cache_hit = True

        content = await documentation_cache.get_resource(uri)

        if content is None:
            error_msg = f"Documentation page not found: {uri}"
            if analytics and config.analytics_enabled:
                await analytics.log_resource_read(
                    resource_uri=uri,
                    success=False,
                    response_time_ms=int((time.time() - start_time) * 1000),
                    error_message="Documentation page not found",
                )
            return error_msg

        # Log successful resource read
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=True,
                response_time_ms=int((time.time() - start_time) * 1000),
                cache_hit=cache_hit,
            )

        return content

    except Exception as e:
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=False,
                response_time_ms=int((time.time() - start_time) * 1000),
                error_message=str(e),
            )
        raise


def main():
    """Start the HTTP server"""

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

        # Run database migrations first (before async context)
        run_migrations()

        # Run with anyio to properly initialize task groups
        anyio.run(run_server_async)

    except KeyboardInterrupt:
        log_startup("\n\nShutting down server...")
        # Cleanup analytics
        analytics = get_analytics_logger()
        if analytics:
            log_startup("📊 Flushing pending analytics events...")
            anyio.run(analytics.cleanup)
        sys.exit(0)
    except Exception as e:
        log_startup(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        # Cleanup analytics on error
        analytics = get_analytics_logger()
        if analytics:
            anyio.run(analytics.cleanup)
        sys.exit(1)


if __name__ == "__main__":
    main()
