#!/usr/bin/env python3

import logging
import sys
from typing import Any

from fastmcp import FastMCP

from mpt_mcp import audit_fields
from mpt_mcp.api_client import APIClient
from mpt_mcp.cache_manager import CacheManager, fetch_with_cache
from mpt_mcp.config import config
from mpt_mcp.endpoint_registry import get_openapi_spec_url
from mpt_mcp.log_config import configure_logging
from mpt_mcp.mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_quick_queries,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
)
from mpt_mcp.openapi_parser import OpenAPIParser

logger = logging.getLogger(__name__)

DEBUG_TAG = "debug"

mcp = FastMCP("softwareone-marketplace")

api_client: APIClient | None = None
endpoints_registry: dict[str, dict[str, Any]] = {}
openapi_spec: dict[str, Any] = {}
cache_manager: CacheManager | None = None
_initialized: bool = False


async def initialize_server(*, force_refresh: bool = False) -> None:
    """
    Initialize the server with API client and discover endpoints.

    Args:
        force_refresh: Force refresh cache even if valid cache exists
    """
    global api_client, endpoints_registry, openapi_spec, cache_manager, _initialized

    if _initialized and not force_refresh:
        return

    # STDIO is for local development - don't use analytics
    logger.info("Analytics disabled (STDIO mode is for local development)")

    errors = config.validate()
    if errors:
        logger.error("Configuration errors:")
        for config_error in errors:
            logger.info("  - %s", config_error)
        raise ValueError("Invalid configuration")

    api_client = APIClient(
        base_url=config.marketplace_api_base_url,
        token=config.marketplace_api_token,
        timeout=config.request_timeout,
    )

    cache_manager = CacheManager(cache_dir=".cache", ttl_hours=24)

    openapi_parser = OpenAPIParser()

    openapi_spec_url = get_openapi_spec_url(api_client.base_url)

    try:
        logger.info("Loading OpenAPI spec from: %s", openapi_spec_url)

        spec = await fetch_with_cache(
            url=openapi_spec_url, cache_manager=cache_manager, force_refresh=force_refresh
        )

        openapi_spec = spec

        for endpoint in openapi_parser.extract_get_endpoints(spec):
            endpoints_registry[_path_to_resource_id(endpoint["path"])] = {
                "path": endpoint["path"],
                "summary": endpoint["summary"],
                "parameters": endpoint["parameters"],
            }

        logger.info("Discovered %s GET endpoints", len(endpoints_registry))
        logger.info("Stored in memory registry with %s resource IDs", len(endpoints_registry))

        try:
            audit_fields.update_cache(config.marketplace_api_base_url, spec, _path_to_resource_id)
            logger.info("Audit fields cache updated")
        except Exception as audit_err:
            logger.warning("Audit fields cache skipped: %s", audit_err)

        _initialized = True

    except Exception as error:
        logger.warning("Failed to load OpenAPI spec: %s", error)
        endpoints_registry = {}
        _initialized = False


def _path_to_resource_id(path: str) -> str:
    """
    Convert an API path to a resource identifier.

    Examples:
        /public/v1/catalog/products -> catalog.products
        /public/v1/catalog/items/{id} -> catalog.items.by_id
        /public/v1/commerce/orders -> commerce.orders
    """
    path = path.replace("/public/v1/", "")
    path = path.replace("/{id}", ".by_id")
    return path.replace("/", ".")


@mcp.tool()
async def marketplace_query(
    resource: str,
    rql: str = "",
    limit: int | None = None,
    offset: int | None = None,
    select: str | None = None,
    order: str | None = None,
    path_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    marketplace_query(resource, rql, limit, offset, select, order): Query the SoftwareOne Marketplace API.

    Query the SoftwareOne Marketplace API using Resource Query Language (RQL).

    Supports both simple queries and advanced RQL filtering, sorting, and pagination. See
    documentation at https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language

    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string. Examples: eq(status,Active), ilike(name,*Microsoft*).
            Dates in UTC (YYYY-MM-DDTHH:MM:SS.mmmZ). Pagination/selection: limit=100,
            select=+status, order=-created.
        limit: Max items to return (default 10, max 100). Use select= with only needed fields
            (from marketplace_resource_schema) to avoid huge responses.
        offset: Number of items to skip for pagination (e.g., 0, 20, 40)
        select: Fields to include/exclude (+name,+description or -metadata). For audit
            fields include 'audit'. Nested: +subscriptions (full), +subscriptions.id,
            +subscriptions.id,+subscriptions.name.
            For catalog.products when including vendor use +vendor.id,+vendor.name (not +vendor).
            RQL filter fields must exist—use marketplace_resource_schema(resource) to check.
        order: Sort order (e.g., -created for descending, +name for ascending). When using
            audit fields (e.g., -audit.created.at), ensure select includes 'audit'.
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
    """  # ruff: ignore[line-too-long]
    if not _initialized:
        await initialize_server()
    if not api_client:
        return {"error": "Server not initialized"}

    audit_regex = audit_fields.get_audit_regex(config.marketplace_api_base_url)
    return await execute_marketplace_query(
        resource=resource,
        rql=rql,
        limit=limit,
        offset=offset,
        select=select,
        order=order,
        path_params=path_params,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
        analytics_logger=None,  # STDIO mode - no analytics
        config=config,
        audit_regex=audit_regex,
        openapi_spec=openapi_spec,
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
    if not _initialized:
        await initialize_server()

    if not endpoints_registry:
        return {"error": "Server not initialized or no endpoints available"}

    return execute_marketplace_resources(
        api_base_url=config.marketplace_api_base_url,
        user_id=None,  # STDIO is single-user
        endpoints_registry=endpoints_registry,
    )


@mcp.tool(tags={DEBUG_TAG})
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
        "note": "Cache reduces startup time and allows offline operation. Cache is automatically "
        "refreshed every 24 hours.",
    }


@mcp.tool(tags={DEBUG_TAG})
async def marketplace_refresh_cache() -> dict[str, Any]:
    """
    Force refresh the OpenAPI spec cache.

    Only listed and callable when DEBUG=true.

    Use this to manually update the endpoint registry if you know the API has changed.

    Returns:
        Status message indicating cache refresh result
    """
    if not cache_manager or not api_client:
        return {"error": "Cache manager not initialized"}

    try:
        logger.info("Force refreshing OpenAPI spec cache...")

        cache_manager.invalidate(get_openapi_spec_url(api_client.base_url))

        await initialize_server(force_refresh=True)

        return {
            "success": True,
            "message": f"Cache refreshed successfully. Loaded {len(endpoints_registry)} endpoints.",
            "endpoints_count": len(endpoints_registry),
        }
    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "message": "Failed to refresh cache. Check network connection.",
        }


@mcp.tool()
async def marketplace_resource_info(resource: str) -> dict[str, Any]:
    """
    marketplace_resource_info(resource): Get detailed information about a specific resource.

    Args:
        resource: The resource identifier (e.g., catalog.products)

    Returns:
        Detailed information about the resource including available parameters
    """
    if not _initialized:
        await initialize_server()

    return execute_marketplace_resource_info(
        resource=resource,
        endpoints_registry=endpoints_registry,
    )


@mcp.tool()
async def marketplace_resource_schema(resource: str) -> dict[str, Any]:
    """
    marketplace_resource_schema(resource): Get the full schema for a resource.

    Returns detailed information about the resource including available parameters, example
    queries, filterable fields, and response structure.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)

    Returns:
        Complete JSON schema with field types, descriptions, enums, and examples

    Example: marketplace_resource_schema(resource=catalog.products) returns full schema; for
    products use select=+vendor.id,+vendor.name when including vendor.
    """
    if not _initialized:
        await initialize_server()

    if not openapi_spec:
        return {"error": "OpenAPI spec not loaded", "hint": "Server initialization may have failed"}

    return execute_marketplace_resource_schema(
        resource=resource,
        openapi_spec=openapi_spec,
        endpoints_registry=endpoints_registry,
    )


@mcp.tool()
async def marketplace_audit_fields(resource: str | None = None) -> dict[str, Any]:
    """
    Get audit event names per resource for filtering by "when" something happened.

    Derived from the OpenAPI spec at startup. Returns event names (e.g. created, updated, failed);
    paths are always audit.<event>.at (when) and audit.<event>.by (who). Use for queries like
    "orders failed starting when" (audit.failed.at) or "agreements created after X"
    (audit.created.at).
    Include select=audit when filtering or sorting by these fields.

    Args:
        resource: Optional. If provided, returns events for this resource only
                  (e.g. commerce.orders). If omitted, returns all resources.

    Returns:
        If resource is set: { "resource": str, "events": [ "created", "updated", ... ] }.
        If resource is omitted:
            { "by_resource": { resource_id: [ "event1", "event2", ... ], ... } }.
    """
    if not _initialized:
        await initialize_server()

    return audit_fields.get_audit_fields(config.marketplace_api_base_url, resource)


# Debug tools are only listed and callable in development
if not config.debug:
    mcp.disable(tags={DEBUG_TAG})


if __name__ == "__main__":
    configure_logging(logging.DEBUG if config.debug else logging.INFO)
    try:
        logger.info("=" * 60)
        logger.info("SoftwareOne Marketplace MCP Server (Stdio Mode)")
        logger.info("=" * 60)
        logger.info("Server will initialize on first tool call...")
        logger.info("Available tools: 7 (streamlined interface with caching)")
        logger.info("Starting server on stdio...")
        logger.info("=" * 60)

        mcp.run()

    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        sys.exit(0)
    except Exception:
        logger.exception("Server error")
        sys.exit(1)
