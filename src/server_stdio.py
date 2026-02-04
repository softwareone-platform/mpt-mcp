#!/usr/bin/env python3
"""
MCP Server for SoftwareOne Marketplace API - Stdio Transport (Local)

This version uses standard I/O for local Cursor integration.
Uses a streamlined tool approach with discriminator pattern.
"""

import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .api_client import APIClient
from .cache_manager import CacheManager, fetch_with_cache
from .config import config
from .mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_quick_queries,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
)
from .openapi_parser import OpenAPIParser

# Initialize FastMCP server
mcp = FastMCP("softwareone-marketplace")

# Global instances
api_client: APIClient | None = None
endpoints_registry: dict[str, dict[str, Any]] = {}
openapi_spec: dict[str, Any] = {}
cache_manager: CacheManager | None = None
_initialized: bool = False


def _log_stderr(message: str) -> None:
    """Print to stderr for tool diagnostics (RQL, params, count). Safe for STDIO (stdout is JSON-RPC only)."""
    print(message, file=sys.stderr, flush=True)


async def initialize_server(force_refresh: bool = False):
    """
    Initialize the server with API client and discover endpoints

    Args:
        force_refresh: Force refresh cache even if valid cache exists
    """
    global api_client, endpoints_registry, openapi_spec, cache_manager, _initialized

    # Skip if already initialized (unless force refresh)
    if _initialized and not force_refresh:
        return

    # Use stderr for all logging
    import sys

    def log(message):
        print(message, file=sys.stderr, flush=True)

    # STDIO is for local development - don't use analytics
    log("📊 Analytics disabled (STDIO mode is for local development)")

    # Validate configuration
    errors = config.validate()
    if errors:
        log("❌ Configuration errors:")
        for error in errors:
            log(f"  - {error}")
        raise ValueError("Invalid configuration")

    api_client = APIClient(base_url=config.marketplace_api_base_url, token=config.marketplace_api_token, timeout=config.request_timeout)

    # Initialize cache manager (24 hour TTL)
    cache_manager = CacheManager(cache_dir=".cache", ttl_hours=24)

    openapi_parser = OpenAPIParser()

    try:
        # Fetch OpenAPI spec (with caching)
        log(f"📡 Loading OpenAPI spec from: {config.openapi_spec_url}")

        # Try to fetch with cache
        spec = await fetch_with_cache(url=config.openapi_spec_url, cache_manager=cache_manager, force_refresh=force_refresh, timeout=30.0)

        # Parse OpenAPI spec and extract GET endpoints
        tools = await openapi_parser.extract_get_endpoints(spec)

        # Store the full OpenAPI spec for schema lookups
        openapi_spec = spec

        # Store endpoint information in memory registry
        for tool in tools:
            tool_info = json.loads(tool.description)
            path = tool_info.get("path", "")

            # Create a resource identifier from the path
            # Example: /public/v1/catalog/products -> catalog.products
            resource_id = _path_to_resource_id(path)

            endpoints_registry[resource_id] = {
                "path": path,
                "summary": tool_info.get("summary", ""),
                "parameters": tool_info.get("parameters", []),
            }

        log(f"✓ Discovered {len(endpoints_registry)} GET endpoints")
        log(f"✓ Stored in memory registry with {len(endpoints_registry)} resource IDs")

        _initialized = True

    except Exception as e:
        log(f"⚠ Failed to load OpenAPI spec: {e}")
        endpoints_registry = {}
        _initialized = False


def _path_to_resource_id(path: str) -> str:
    """
    Convert an API path to a resource identifier

    Examples:
        /public/v1/catalog/products -> catalog.products
        /public/v1/catalog/items/{id} -> catalog.items.by_id
        /public/v1/commerce/orders -> commerce.orders
    """
    # Remove /public/v1/ prefix
    path = path.replace("/public/v1/", "")

    # Replace path parameters with descriptive names
    path = path.replace("/{id}", ".by_id")

    # Replace slashes with dots
    resource_id = path.replace("/", ".")

    return resource_id


def _build_resource_enum() -> list[str]:
    """Build list of available resource IDs for the enum"""
    return sorted(endpoints_registry.keys())


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

    Supports both simple queries and advanced RQL filtering, sorting, and pagination. See documentation at https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language

    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string for complex filtering and sorting. Examples: eq(status,Active), and(eq(status,Active),gt(price,100)), ilike(name,*Microsoft*). Dates use UTC format YYYY-MM-DDTHH:MM:SS.mmmZ (e.g. 2026-01-31T23:00:00.000Z). Note: Pagination and selection use key=value syntax like limit=100, select=+status, order=-created
        limit: Maximum number of items to return (e.g., 10, 50, 100). Defaults to 10 if not specified. Maximum allowed is 100 (values above 100 are capped to 100). When using limit up to 100, use select= with only the fields you need (from marketplace_resource_schema) to avoid huge responses.
        offset: Number of items to skip for pagination (e.g., 0, 20, 40)
        page: Page number (alternative to offset)
        select: Fields to include/exclude (e.g., +name,+description or -metadata). IMPORTANT: When filtering or sorting by audit fields (e.g., audit.created.at), you must include 'audit' in select. Dates in RQL use UTC: YYYY-MM-DDTHH:MM:SS.mmmZ (e.g. 2026-01-31T23:00:00.000Z). The server will auto-add this if detected. For nested collections: +subscriptions returns the full nested representation (each item as a full object); +subscriptions.id returns only the ids of the nested collection; +subscriptions.id,+subscriptions.name returns only id and name per nested item. Prefer +subscriptions.id,+subscriptions.name when you only need to count or show id/name. RQL filter fields must exist on the resource—use marketplace_resource_schema(resource) to check (e.g. subscriptionsCount does not exist).
        order: Sort order (e.g., -created for descending, +name for ascending). When using audit fields (e.g., -audit.created.at), ensure select includes 'audit'.
        path_params: Path parameters for resources requiring IDs
            Examples: {id: PRD-1234-5678} for catalog.products.by_id
                     {orderId: ORD-1234-5678} for commerce.orders.{orderId}.lines

    Returns:
        API response with data and pagination information

    Available Resource Categories:
    - Catalog: catalog.products, catalog.items, catalog.listings, catalog.authorizations
    - Commerce: commerce.orders, commerce.requests, commerce.agreements, commerce.subscriptions
    - Billing: billing.invoices, billing.statements, billing.journals, billing.ledgers
    - Accounts: accounts.accounts, accounts.buyers, accounts.sellers, accounts.users

    RQL Query Examples:
    - Pagination: limit=10, offset=0
    - Filter: rql=eq(status,Active), limit=20
    - Search: rql=ilike(name,*Microsoft*), limit=50
    - Complex: rql=and(eq(status,Active),gt(price,100)), order=-created
    - Sort: order=-created or order=+name

    Use marketplace_resources() to see all available resources.
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()
    if not api_client:
        return {"error": "Server not initialized"}

    # Use shared implementation
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
        endpoints_registry=endpoints_registry,
        log_fn=None,  # use logger only (no duplicate print)
        analytics_logger=None,  # STDIO mode - no analytics
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

    Returns a categorized list of all available API endpoints.
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()

    if not endpoints_registry:
        return {"error": "Server not initialized or no endpoints available"}

    # Use shared implementation
    return await execute_marketplace_resources(
        api_base_url=config.marketplace_api_base_url,
        user_id=None,  # STDIO is single-user
        endpoints_registry=endpoints_registry,
    )


@mcp.tool()
async def marketplace_cache_info() -> dict[str, Any]:
    """
    Get information about the OpenAPI spec cache.

    Shows cache statistics, expiration time, and allows cache management.

    Returns:
        Cache statistics and information
    """
    if not cache_manager:
        return {"error": "Cache manager not initialized"}

    cache_info = cache_manager.get_cache_info()

    return {
        "cache_status": "enabled",
        "cache_info": cache_info,
        "note": "Cache reduces startup time and allows offline operation. Cache is automatically refreshed every 24 hours.",
    }


@mcp.tool()
async def marketplace_refresh_cache() -> dict[str, Any]:
    """
    Force refresh the OpenAPI spec cache.

    ⚠️  DEVELOPMENT ONLY - Not available in production for security reasons.

    Use this to manually update the endpoint registry if you know the API has changed.

    Returns:
        Status message indicating cache refresh result
    """
    # Security: Only allow cache refresh in development mode
    if not config.debug:
        return {
            "error": "Access denied",
            "message": "Cache refresh is only available in development mode (DEBUG=true).",
            "hint": "This tool is disabled in production for security reasons.",
        }

    if not cache_manager:
        return {"error": "Cache manager not initialized"}

    try:
        print("🔄 Force refreshing OpenAPI spec cache...")

        # Invalidate current cache
        cache_manager.invalidate(config.openapi_spec_url)

        # Re-initialize server (will fetch fresh data)
        await initialize_server(force_refresh=True)

        return {
            "success": True,
            "message": f"Cache refreshed successfully. Loaded {len(endpoints_registry)} endpoints.",
            "endpoints_count": len(endpoints_registry),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "message": "Failed to refresh cache. Check network connection."}


@mcp.tool()
async def marketplace_resource_info(resource: str) -> dict[str, Any]:
    """
    marketplace_resource_info(resource): Get detailed information about a specific resource.

    Args:
        resource: The resource identifier (e.g., catalog.products)

    Returns:
        Detailed information about the resource including available parameters
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()

    # Use shared implementation
    return await execute_marketplace_resource_info(
        resource=resource,
        endpoints_registry=endpoints_registry,
    )


@mcp.tool()
async def marketplace_resource_schema(resource: str) -> dict[str, Any]:
    """
    marketplace_resource_schema(resource): Get the full schema for a resource.

    Returns detailed information about the resource including available parameters, example queries, filterable fields, and response structure.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)

    Returns:
        Complete JSON schema with field types, descriptions, enums, and examples

    Example: marketplace_resource_schema(resource=catalog.products) returns full schema showing all product fields like id, name, status, vendor, etc.
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()

    # Use the global OpenAPI spec
    if not openapi_spec:
        return {"error": "OpenAPI spec not loaded", "hint": "Server initialization may have failed"}

    # Use shared implementation
    return await execute_marketplace_resource_schema(
        resource=resource,
        openapi_spec=openapi_spec,
        endpoints_registry=endpoints_registry,
    )


if __name__ == "__main__":
    import sys

    # Send all logs to stderr (stdout is for JSON-RPC only!)
    def log(message):
        print(message, file=sys.stderr, flush=True)

    try:
        log("=" * 60)
        log("🚀 SoftwareOne Marketplace MCP Server (Stdio Mode)")
        log("=" * 60)
        log("\nServer will initialize on first tool call...")
        log("Available tools: 7 (streamlined interface with caching)")
        log("\n✓ Starting server on stdio...")
        log("=" * 60 + "\n")

        # Start the MCP server (initialization happens on first tool call)
        mcp.run()

    except KeyboardInterrupt:
        log("\n\nShutting down server...")
        sys.exit(0)
    except Exception as e:
        log(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
