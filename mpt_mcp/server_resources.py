import json
import time
from typing import Any

from . import endpoint_registry, server_docs
from .analytics import get_analytics_logger
from .config import config
from .server_context import get_current_credentials


async def get_openapi_spec() -> str:
    """Return OpenAPI spec for the current endpoint (requires auth)."""
    analytics = get_analytics_logger()
    start_time = time.time()
    uri = "api://openapi.json"
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
    try:
        cache_hit = endpoint in endpoint_registry._openapi_specs
        openapi_spec = await endpoint_registry.get_openapi_spec(endpoint, force_refresh=False)
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
        spec_with_metadata = {
            "api_endpoint": endpoint,
            "authenticated_as": token_info.get("account", {}).get("name", "Unknown") if token_info else "Unknown",
            "account_id": token_info.get("account", {}).get("id", "Unknown") if token_info else "Unknown",
            "openapi_version": openapi_spec.get("openapi", "3.0"),
            "info": openapi_spec.get("info", {}),
            "spec": openapi_spec,
        }
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=True,
                response_time_ms=int((time.time() - start_time) * 1000),
                cache_hit=cache_hit,
            )
        return json.dumps(spec_with_metadata, indent=2)
    except Exception as e:
        error_response = json.dumps(
            {"error": "Failed to fetch OpenAPI specification", "message": str(e), "endpoint": endpoint},
            indent=2,
        )
        if analytics and config.analytics_enabled:
            await analytics.log_resource_read(
                resource_uri=uri,
                success=False,
                response_time_ms=int((time.time() - start_time) * 1000),
                error_message=str(e),
            )
        return error_response


def register_http_resources(mcp: Any) -> None:
    mcp.resource(
        "api://openapi.json",
        name="OpenAPI Specification",
        description="OpenAPI 3 spec for the current API endpoint (requires auth).",
        mime_type="application/json",
    )(get_openapi_spec)

    @mcp.resource(
        "docs://{path}",
        name="Documentation",
        description="Documentation pages. Use marketplace_docs_list() for available URIs.",
        mime_type="text/markdown",
    )
    async def get_documentation_resource(path: str) -> str:
        analytics = get_analytics_logger()
        start_time = time.time()
        uri = f"docs://{path}"
        try:
            await server_docs.initialize_documentation_cache()
            dc = server_docs.documentation_cache
            if not dc or not dc.is_enabled:
                error_msg = "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
                if analytics and config.analytics_enabled:
                    await analytics.log_resource_read(
                        resource_uri=uri,
                        success=False,
                        response_time_ms=int((time.time() - start_time) * 1000),
                        error_message=error_msg,
                    )
                return error_msg
            cache_hit = False
            if uri in dc._resources:
                resource = dc._resources[uri]
                if resource.get("content") is not None:
                    cache_hit = True
            content = await dc.get_resource(uri)
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
