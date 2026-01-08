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

import sys
from typing import Any
from contextvars import ContextVar
import os

import anyio
import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .openapi_parser import OpenAPIParser
from .api_client import APIClient
from .config import config
from .cache_manager import CacheManager, fetch_with_cache
from . import endpoint_registry

# ============================================================================
# Context Variables for request-scoped data (like SSE server)
# ============================================================================

# Context variables for structured logging and credential passing
_current_session_id: ContextVar[str | None] = ContextVar('current_session_id', default=None)
_current_user_id: ContextVar[str | None] = ContextVar('current_user_id', default=None)
_current_token: ContextVar[str | None] = ContextVar('current_token', default=None)
_current_endpoint: ContextVar[str | None] = ContextVar('current_endpoint', default=None)


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

class CredentialsMiddleware:
    """
    ASGI middleware that extracts credentials from HTTP headers and stores
    them in ContextVars, making them available to tool functions.
    
    This is the same pattern as the SSE server but adapted for streamable-http.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Extract credentials from headers (case-insensitive)
            auth_header = request.headers.get('x-mpt-authorization') or request.headers.get('X-MPT-Authorization')
            endpoint_header = request.headers.get('x-mpt-endpoint') or request.headers.get('X-MPT-Endpoint')
            
            # Extract user ID from token for logging
            user_id = None
            if auth_header:
                user_id = APIClient._extract_user_id(auth_header)
            
            # Extract session ID from query params or generate one
            session_id = request.query_params.get('session_id')
            
            # Set context variables for this request
            token_ctx = user_ctx = session_ctx = endpoint_ctx = None
            
            if auth_header:
                token_ctx = _current_token.set(auth_header)
            if endpoint_header:
                endpoint_ctx = _current_endpoint.set(endpoint_header)
            if user_id:
                user_ctx = _current_user_id.set(user_id)
            if session_id:
                session_ctx = _current_session_id.set(session_id)
            
            try:
                # Log request for debugging
                if request.url.path == "/mcp":
                    log(f"🔍 HTTP {request.method} {request.url.path}")
                    log(f"   Token: {'✓ present' if auth_header else '✗ MISSING'}")
                    log(f"   Endpoint: {endpoint_header or config.sse_default_base_url}")
                    if user_id:
                        log(f"   User: {user_id}")
                
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
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
    allowed_hosts=["*"],
    allowed_origins=["*"]
)

# Get port from environment (Cloud Run sets PORT)
server_port = int(os.getenv("PORT", "8080"))
server_host = "0.0.0.0"  # Bind to all interfaces for Cloud Run

print(f"✅ Transport security configured for public API", file=sys.stderr, flush=True)
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

# Global cache manager
cache_manager: CacheManager | None = None
_cache_initialized: bool = False


async def initialize_cache():
    """Initialize the shared cache manager"""
    global cache_manager, _cache_initialized
    
    if _cache_initialized:
        return
    
    cache_manager = CacheManager(cache_dir=".cache", ttl_hours=24)
    _cache_initialized = True
    log(f"✓ Cache manager initialized")


def normalize_endpoint_url(endpoint: str) -> str:
    """Normalize the API endpoint URL by removing trailing paths like /public"""
    if not endpoint:
        return endpoint
    
    endpoint = endpoint.rstrip('/')
    
    if endpoint.endswith('/public'):
        endpoint = endpoint[:-7]
    
    return endpoint


def get_current_credentials() -> tuple[str | None, str]:
    """Get credentials from the current request context (set by middleware)."""
    token = _current_token.get()
    endpoint = _current_endpoint.get() or config.sse_default_base_url
    return token, normalize_endpoint_url(endpoint)


async def get_client_api_client_http() -> APIClient:
    """Get an API client using credentials from the current request context."""
    token, endpoint = get_current_credentials()
    
    if not token:
        raise ValueError(
            "Missing X-MPT-Authorization header. "
            "Please provide your API token in the X-MPT-Authorization header."
        )
    
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
    path_params: dict[str, str] | None = None
) -> dict[str, Any]:
    """
    Query the SoftwareOne Marketplace API using Resource Query Language (RQL).
    
    MULTI-TENANT MODE: This server accepts client credentials via HTTP headers. Pass X-MPT-Authorization with your SoftwareOne API token (required, case-insensitive). Optionally pass X-MPT-Endpoint to specify API endpoint (defaults to api.platform.softwareone.com, case-insensitive).
    
    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string for complex filtering and sorting. Examples: eq(status,Active), and(eq(status,Active),gt(price,100)), ilike(name,*Microsoft*). Note: Pagination and selection use key=value syntax like limit=100, select=+status, order=-created
        limit: Maximum number of items to return (e.g., 10, 50, 100)
        offset: Number of items to skip for pagination (e.g., 0, 20, 40)
        page: Page number (alternative to offset)
        select: Fields to include/exclude (e.g., +name,+description or -metadata)
        order: Sort order (e.g., -created for descending, +name for ascending)
        path_params: Path parameters for resources requiring IDs (e.g., {id: PRD-1234-5678} for catalog.products.by_id, {orderId: ORD-1234-5678} for commerce.orders.{orderId}.lines)
    
    Returns:
        API response with data and pagination information
    
    Use marketplace_resources() to see all available resources.
    """
    await initialize_cache()
    
    # Get credentials from request context (set by middleware)
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}
    
    # Get endpoints registry for this client's API endpoint (like SSE server does)
    api_base_url = api_client.base_url
    log(f"🔍 Using API endpoint: {api_base_url}")
    
    try:
        endpoints_registry = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {
            "error": "Failed to load OpenAPI spec for your endpoint",
            "api_endpoint": api_base_url,
            "details": str(e),
            "hint": f"Ensure {api_base_url}/public/v1/openapi.json is accessible"
        }
    
    if resource not in endpoints_registry:
        return {
            "error": f"Unknown resource: {resource}",
            "hint": "Use marketplace_resources() to see all available resources",
            "available_categories": list(set(r.split('.')[0] for r in endpoints_registry.keys()))
        }
    
    endpoint_info = endpoints_registry[resource]
    api_path = endpoint_info["path"]
    
    # Replace path parameters (e.g., {id}, {productId}, etc.)
    import re
    if path_params:
        for param_name, param_value in path_params.items():
            # Replace {param_name} in the path
            api_path = api_path.replace(f"{{{param_name}}}", str(param_value))
    
    # Check if there are still unresolved path parameters
    remaining_params = re.findall(r'\{(\w+)\}', api_path)
    if remaining_params:
        return {
            "error": f"Missing required path parameters: {', '.join(remaining_params)}",
            "resource": resource,
            "path_template": endpoint_info["path"],
            "hint": f"Provide path_params like: {{{', '.join([f'{p}: value' for p in remaining_params])}}}"
        }
    
    params = {}
    if rql:
        params["rql"] = rql
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if page is not None:
        params["page"] = page
    if select:
        params["select"] = select
    if order:
        params["order"] = order
    
    log(f"📊 Query: {resource}")
    log(f"   Path: {api_path}")
    log(f"   Params: {params}")
    
    try:
        result = await api_client.get(api_path, params=params)
        if "$meta" in result:
            log(f"   ✅ Result: {result['$meta'].get('pagination', {}).get('total', '?')} total items")
        return result
    except Exception as e:
        log(f"   ❌ Error: {e}")
        return {"error": str(e), "resource": resource, "path": api_path}


@mcp.tool()
async def marketplace_resources() -> dict[str, Any]:
    """
    List all available resources in the SoftwareOne Marketplace API with detailed information.
    
    Returns a categorized list of all available API endpoints including resource paths and summaries, common filterable fields (when available), example queries per resource, and response structure hints.
    
    Returns:
        Detailed resource catalog organized by category
    
    Example: marketplace_resources() shows all available resources like catalog.products, commerce.orders, etc. with filtering hints and example queries for each.
    """
    await initialize_cache()
    
    # Get credentials from request context
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}
    
    # Get endpoints registry for this client's API endpoint
    api_base_url = api_client.base_url
    
    try:
        endpoints_registry = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {
            "error": "Failed to load OpenAPI spec",
            "details": str(e)
        }
    
    # Build enhanced categories with more metadata
    categories = {}
    for resource_name, endpoint_info in endpoints_registry.items():
        category = resource_name.split('.')[0]
        if category not in categories:
            categories[category] = []
        
        # Build resource entry with enhanced information
        resource_entry = {
            "resource": resource_name,
            "summary": endpoint_info["summary"],
            "path": endpoint_info["path"],
        }
        
        # Add description if available
        if endpoint_info.get("description"):
            resource_entry["description"] = endpoint_info["description"]
        
        # Extract common filterable fields from parameters
        parameters = endpoint_info.get("parameters", [])
        filterable_fields = []
        enum_fields = {}
        
        for param in parameters:
            param_name = param.get("name", "")
            if param.get("in") == "query" and param_name:
                filterable_fields.append(param_name)
                
                # Check for enum values
                param_schema = param.get("schema", {})
                if "enum" in param_schema:
                    enum_fields[param_name] = param_schema["enum"]
        
        if filterable_fields:
            resource_entry["filterable_fields"] = filterable_fields[:5]  # Limit to first 5
        
        if enum_fields:
            resource_entry["enum_fields"] = enum_fields
        
        # Add common query examples based on resource type
        examples = []
        
        # Basic listing
        examples.append(f"marketplace_query(resource='{resource_name}', limit=10)")
        
        # Add filter examples if we know common fields
        if "status" in filterable_fields or any("status" in ef for ef in enum_fields):
            if "status" in enum_fields:
                status_value = enum_fields["status"][0] if enum_fields["status"] else "Active"
            else:
                status_value = "Active"
            examples.append(f"marketplace_query(resource='{resource_name}', rql='eq(status,{status_value})', limit=20)")
        
        # Add search example for resources that likely have name fields
        if "name" in filterable_fields or resource_name.endswith((".products", ".items", ".vendors")):
            examples.append(f"marketplace_query(resource='{resource_name}', rql='ilike(name,*keyword*)', limit=10)")
        
        resource_entry["example_queries"] = examples
        
        # Add hint about getting full schema
        resource_entry["get_full_schema"] = f"marketplace_resource_schema(resource='{resource_name}')"
        
        categories[category].append(resource_entry)
    
    user_id = _current_user_id.get() or "unknown"
    
    return {
        "api_endpoint": api_base_url,
        "user": user_id,
        "total_resources": len(endpoints_registry),
        "categories": categories,
        "usage": {
            "query_resource": "Use marketplace_query(resource='category.resource', ...) to query any resource",
            "get_schema": "Use marketplace_resource_schema(resource='...') to see full field list and types",
            "get_details": "Use marketplace_resource_info(resource='...') for parameter details"
        },
        "tips": {
            "filtering": "Use RQL for complex filters: eq(field,value), ilike(name,*keyword*), and(condition1,condition2)",
            "pagination": "Use limit= and offset= parameters for pagination",
            "sorting": "Use order= parameter: order=-created (descending), order=+name (ascending)",
            "field_selection": "Use select= parameter: select=+id,+name,+status or select=-metadata"
        }
    }


@mcp.tool()
async def marketplace_resource_info(resource: str) -> dict[str, Any]:
    """
    Get detailed information about a specific marketplace resource.
    
    Args:
        resource: The resource to get information about (e.g., catalog.products)
    
    Returns:
        Detailed resource information including path, parameters, and response schema
    """
    await initialize_cache()
    
    # Get credentials from request context
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}
    
    # Get endpoints registry for this client's API endpoint
    api_base_url = api_client.base_url
    
    try:
        endpoints_registry = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {
            "error": "Failed to load OpenAPI spec",
            "details": str(e)
        }
    
    if resource not in endpoints_registry:
        return {
            "error": f"Unknown resource: {resource}",
            "hint": "Use marketplace_resources() to see all available resources"
        }
    
    endpoint_info = endpoints_registry[resource]
    
    # Extract enum values from parameters
    enum_fields = {}
    path_params_info = {}
    
    for param in endpoint_info.get("parameters", []):
        param_name = param.get("name")
        param_in = param.get("in")
        param_schema = param.get("schema", {})
        
        # Track path parameters
        if param_in == "path":
            path_params_info[param_name] = {
                "type": param_schema.get("type", "string"),
                "description": param.get("description", f"Path parameter: {param_name}"),
                "required": param.get("required", True)
            }
        
        # Extract enum values for query parameters
        if "enum" in param_schema and param_in == "query":
            enum_fields[param_name] = param_schema["enum"]
    
    result = {
        "resource": resource,
        "path": endpoint_info["path"],
        "summary": endpoint_info["summary"],
        "description": endpoint_info.get("description", ""),
        "parameters": endpoint_info["parameters"],
        "response_schema": endpoint_info.get("response", {}),
        "common_parameters": {
            "rql": "RQL query string for filtering and sorting",
            "limit": "Maximum number of items to return",
            "offset": "Number of items to skip",
            "page": "Page number",
            "select": "Fields to include/exclude",
            "order": "Sort order (e.g., -created for descending, +name for ascending)",
            "path_params": "Dictionary of path parameters (e.g., {id: PRD-1234-5678})"
        },
        "example_usage": f"marketplace_query(resource='{resource}', limit=10)"
    }
    
    # Add enum fields if any found
    if enum_fields:
        result["enum_fields"] = enum_fields
    
    # Add path parameters info if any found
    if path_params_info:
        result["path_parameters"] = path_params_info
        # Update example to show path_params usage
        example_params = {k: f"<{k}_value>" for k in path_params_info.keys()}
        result["example_usage"] = f"marketplace_query(resource='{resource}', path_params={example_params}, limit=10)"
    
    return result


@mcp.tool()
async def marketplace_resource_schema(resource: str) -> dict[str, Any]:
    """
    Get the complete JSON schema for a marketplace resource.
    
    This returns the detailed schema including all fields, types, nested structures, and descriptions. Useful for understanding what fields are available for filtering and what the response structure will be.
    
    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)
    
    Returns:
        Complete JSON schema with field types, descriptions, enums, and examples
    
    Example: marketplace_resource_schema(resource=catalog.products) returns full schema showing all product fields like id, name, status, vendor, etc.
    """
    await initialize_cache()
    
    # Get credentials from request context
    try:
        api_client = await get_client_api_client_http()
    except ValueError as e:
        return {"error": str(e), "hint": "Provide X-MPT-Authorization header with your API token"}
    
    # Get the OpenAPI spec and endpoints registry
    api_base_url = api_client.base_url
    
    try:
        spec = await endpoint_registry.get_openapi_spec(api_base_url)
        endpoints_registry = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as e:
        return {
            "error": "Failed to load OpenAPI spec",
            "details": str(e)
        }
    
    if resource not in endpoints_registry:
        return {
            "error": f"Unknown resource: {resource}",
            "hint": "Use marketplace_resources() to see all available resources",
            "available_categories": list(set(r.split('.')[0] for r in endpoints_registry.keys()))
        }
    
    endpoint_info = endpoints_registry[resource]
    path = endpoint_info["path"]
    
    # Find the endpoint in the OpenAPI spec
    paths = spec.get("paths", {})
    if path not in paths:
        return {
            "error": f"Path {path} not found in OpenAPI spec",
            "resource": resource
        }
    
    path_item = paths[path]
    if "get" not in path_item:
        return {
            "error": f"GET operation not found for {path}",
            "resource": resource
        }
    
    get_op = path_item["get"]
    
    # Extract response schema
    responses = get_op.get("responses", {})
    schema_info = {
        "resource": resource,
        "path": path,
        "summary": get_op.get("summary", ""),
        "description": get_op.get("description", ""),
    }
    
    if "200" in responses:
        response_200 = responses["200"]
        content = response_200.get("content", {})
        
        if "application/json" in content:
            json_content = content["application/json"]
            if "schema" in json_content:
                schema = json_content["schema"]
                
                # If schema references components, try to resolve it
                if "$ref" in schema:
                    ref_path = schema["$ref"].split("/")
                    ref_schema = spec
                    for part in ref_path:
                        if part and part != "#":
                            ref_schema = ref_schema.get(part, {})
                    schema = ref_schema
                
                schema_info["response_schema"] = schema
                
                # Extract field information from properties
                if "properties" in schema:
                    fields = {}
                    for field_name, field_schema in schema["properties"].items():
                        field_info = {
                            "type": field_schema.get("type", "unknown"),
                            "description": field_schema.get("description", "")
                        }
                        
                        if "enum" in field_schema:
                            field_info["enum"] = field_schema["enum"]
                            field_info["valid_values"] = field_schema["enum"]
                        
                        if "example" in field_schema:
                            field_info["example"] = field_schema["example"]
                        
                        if "format" in field_schema:
                            field_info["format"] = field_schema["format"]
                        
                        # For nested objects, show structure
                        if field_schema.get("type") == "object" and "properties" in field_schema:
                            nested_fields = {}
                            for nested_name, nested_schema in list(field_schema["properties"].items())[:5]:
                                nested_fields[nested_name] = {
                                    "type": nested_schema.get("type", "unknown"),
                                    "description": nested_schema.get("description", "")
                                }
                            field_info["nested_fields"] = nested_fields
                        
                        fields[field_name] = field_info
                    
                    schema_info["fields"] = fields
                    
                    # Add filtering hints
                    schema_info["filtering_hints"] = {
                        "simple_filters": [f"eq({f},value)" for f in list(fields.keys())[:5]],
                        "search_fields": [f"ilike({f},*keyword*)" for f, info in list(fields.items())[:3] if info.get("type") == "string"],
                        "enum_filters": [f"eq({f},{info['enum'][0]})" for f, info in fields.items() if "enum" in info][:3]
                    }
    
    # Add common query patterns
    schema_info["common_queries"] = {
        "basic": f"{resource}?limit=10",
        "with_filters": f"{resource}?eq(status,Active)&limit=20",
        "with_sorting": f"{resource}?order=-id&limit=10",
        "full_example": f"{resource}?eq(status,Active)&order=-id&select=+id,+name,+status&limit=50"
    }
    
    return schema_info


# ============================================================================
# Server Startup with Middleware
# ============================================================================

async def run_server_async():
    """Run the HTTP server with middleware for credential extraction."""
    
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
                    response = JSONResponse({
                        "status": "healthy",
                        "service": "mpt-mcp-http",
                        "transport": "streamable-http",
                        "endpoint": "/mcp"
                    })
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)
    
    final_app = HealthCheckMiddleware(wrapped_app)
    
    print("✅ Middleware added: CredentialsMiddleware, HealthCheckMiddleware", file=sys.stderr, flush=True)
    
    # Run with uvicorn
    uvicorn_config = uvicorn.Config(
        final_app,
        host=server_host,
        port=server_port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


def main():
    """Start the HTTP server"""
    def log_startup(message):
        print(message, file=sys.stderr, flush=True)
    
    try:
        log_startup("=" * 60)
        log_startup("🚀 SoftwareOne Marketplace MCP Server (HTTP Mode)")
        log_startup("=" * 60)
        log_startup(f"\n🌐 Starting server on {server_host}:{server_port}")
        log_startup(f"📡 Transport: Streamable HTTP (POST/DELETE)")
        log_startup(f"📡 Endpoint path: /mcp")
        log_startup(f"📡 Default API endpoint: {config.sse_default_base_url}")
        log_startup("\n🔑 Multi-tenant Authentication:")
        log_startup("   - Clients MUST provide X-MPT-Authorization header")
        log_startup("   - Optional X-MPT-Endpoint header for custom endpoints")
        log_startup("   - Headers are case-insensitive")
        log_startup(f"\n✓ Server URL: http://{server_host}:{server_port}/mcp")
        log_startup(f"✓ Health check: http://{server_host}:{server_port}/health")
        log_startup("=" * 60 + "\n")
        
        # Run with anyio to properly initialize task groups
        anyio.run(run_server_async)
        
    except KeyboardInterrupt:
        log_startup("\n\nShutting down server...")
        sys.exit(0)
    except Exception as e:
        log_startup(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
