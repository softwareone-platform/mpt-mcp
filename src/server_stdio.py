#!/usr/bin/env python3
"""
MCP Server for SoftwareOne Marketplace API - Stdio Transport (Local)

This version uses standard I/O for local Cursor integration.
Uses a streamlined tool approach with discriminator pattern.
"""

import asyncio
import json
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .openapi_parser import OpenAPIParser
from .api_client import APIClient
from .config import config
from .cache_manager import CacheManager, fetch_with_cache

# Initialize FastMCP server
mcp = FastMCP("softwareone-marketplace")

# Global instances
api_client: APIClient | None = None
endpoints_registry: dict[str, dict[str, Any]] = {}
cache_manager: CacheManager | None = None
_initialized: bool = False


async def initialize_server(force_refresh: bool = False):
    """
    Initialize the server with API client and discover endpoints
    
    Args:
        force_refresh: Force refresh cache even if valid cache exists
    """
    global api_client, endpoints_registry, cache_manager, _initialized
    
    # Skip if already initialized (unless force refresh)
    if _initialized and not force_refresh:
        return
    
    # Use stderr for all logging
    import sys
    def log(message):
        print(message, file=sys.stderr, flush=True)

    # Validate configuration
    errors = config.validate()
    if errors:
        log("❌ Configuration errors:")
        for error in errors:
            log(f"  - {error}")
        raise ValueError("Invalid configuration")

    api_client = APIClient(
        base_url=config.marketplace_api_base_url,
        token=config.marketplace_api_token,
        timeout=config.request_timeout
    )

    # Initialize cache manager (24 hour TTL)
    cache_manager = CacheManager(cache_dir=".cache", ttl_hours=24)

    openapi_parser = OpenAPIParser()

    try:
        # Fetch OpenAPI spec (with caching)
        log(f"📡 Loading OpenAPI spec from: {config.openapi_spec_url}")
        
        # Try to fetch with cache
        spec = await fetch_with_cache(
            url=config.openapi_spec_url,
            cache_manager=cache_manager,
            force_refresh=force_refresh,
            timeout=10.0
        )

        # Parse OpenAPI spec and extract GET endpoints
        tools = await openapi_parser.extract_get_endpoints(spec)
        
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
    order: str | None = None
) -> dict[str, Any]:
    """
    Query the SoftwareOne Marketplace API using Resource Query Language (RQL).
    
    Supports both simple queries and advanced RQL filtering, sorting, and pagination. See documentation at https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language
    
    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string for complex filtering and sorting. Examples: eq(status,Active), and(eq(status,Active),gt(price,100)), ilike(name,*Microsoft*). Note: Pagination and selection use key=value syntax like limit=100, select=+status, order=-created
        limit: Maximum number of items to return (e.g., 10, 50, 100)
        offset: Number of items to skip for pagination (e.g., 0, 20, 40)
        page: Page number (alternative to offset)
        select: Fields to include/exclude (e.g., +name,+description or -metadata)
        order: Sort order (e.g., -created for descending, +name for ascending)
    
    Returns:
        API response with data and pagination information
    
    Available Resource Categories: Catalog (catalog.products, catalog.items, catalog.listings, catalog.authorizations), Commerce (commerce.orders, commerce.requests, commerce.agreements, commerce.subscriptions), Billing (billing.invoices, billing.statements, billing.journals, billing.ledgers), Accounts (accounts.accounts, accounts.buyers, accounts.sellers, accounts.users)
    
    RQL Query Examples: Simple pagination (limit=10, offset=0), Filter by status (rql=eq(status,Active), limit=20), Search by name (rql=ilike(name,*Microsoft*), limit=50), Complex filter (rql=and(eq(status,Active),gt(price,100)), order=-created), Sort results (order=-created or order=+name)
    
    Use marketplace_resources() to see all available resources.
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()
    if not api_client:
        return {"error": "Server not initialized"}
    
    # Check if resource exists
    if resource not in endpoints_registry:
        available = _build_resource_enum()
        return {
            "error": f"Unknown resource: {resource}",
            "available_resources": available[:20],  # Show first 20
            "total_available": len(available)
        }
    
    endpoint_info = endpoints_registry[resource]
    path = endpoint_info["path"]
    
    # Build query parameters
    params = {}
    
    # Add RQL if provided
    if rql:
        params["rql"] = rql
    
    # Add pagination parameters
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if page is not None:
        params["page"] = page
    
    # Add select parameter
    if select is not None:
        params["select"] = select
    
    # Add order parameter
    if order is not None:
        params["order"] = order
    
    try:
        result = await api_client.get(path, params=params)
        return result
    except Exception as e:
        return {"error": str(e), "resource": resource, "path": path}


@mcp.tool()
async def marketplace_resources() -> dict[str, Any]:
    """
    List all available marketplace resources that can be queried.
    
    Returns a categorized list of all available API endpoints.
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()
    
    if not endpoints_registry:
        return {"error": "Server not initialized or no endpoints available"}
    
    # Group resources by category
    categories: dict[str, list[dict[str, str]]] = {}
    
    for resource_id, endpoint_info in sorted(endpoints_registry.items()):
        # Extract category from resource_id (first part before dot)
        parts = resource_id.split(".")
        category = parts[0] if parts else "other"
        
        if category not in categories:
            categories[category] = []
        
        categories[category].append({
            "resource": resource_id,
            "summary": endpoint_info["summary"],
            "path": endpoint_info["path"]
        })
    
    return {
        "total_resources": len(endpoints_registry),
        "categories": categories,
        "usage": "Use marketplace_query(resource='category.resource', ...) to query any resource"
    }


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
        "note": "Cache reduces startup time and allows offline operation. Cache is automatically refreshed every 24 hours."
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
            "hint": "This tool is disabled in production for security reasons."
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
            "endpoints_count": len(endpoints_registry)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to refresh cache. Check network connection."
        }


@mcp.tool()
async def marketplace_resource_info(resource: str) -> dict[str, Any]:
    """
    Get detailed information about a specific marketplace resource.
    
    Args:
        resource: The resource identifier (e.g., catalog.products)
    
    Returns:
        Detailed information about the resource including available parameters
    """
    # Ensure server is initialized
    if not _initialized:
        await initialize_server()
    
    if resource not in endpoints_registry:
        return {
            "error": f"Unknown resource: {resource}",
            "hint": "Use marketplace_resources() to see all available resources"
        }
    
    endpoint_info = endpoints_registry[resource]
    
    return {
        "resource": resource,
        "path": endpoint_info["path"],
        "summary": endpoint_info["summary"],
        "parameters": endpoint_info["parameters"],
        "common_parameters": {
            "rql": "RQL query string for filtering and sorting",
            "limit": "Maximum number of items to return",
            "offset": "Number of items to skip",
            "page": "Page number",
            "select": "Fields to include/exclude"
        },
        "example_usage": f"marketplace_query(resource='{resource}', rql='limit=10')"
    }


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
        log("Available tools: 5 (streamlined interface with caching)")
        log("\n✓ Starting server on stdio...")
        log("=" * 60 + "\n")
        
        # Start the MCP server (initialization happens on first tool call)
        # mcp.run() is synchronous and manages its own event loop
        mcp.run()
        
    except KeyboardInterrupt:
        log("\n\nShutting down server...")
        sys.exit(0)
    except Exception as e:
        log(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

