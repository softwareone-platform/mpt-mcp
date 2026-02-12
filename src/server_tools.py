import time
from typing import Any

from . import (
    audit_fields as audit_fields_module,
    endpoint_registry,
)
from .analytics import get_analytics_logger
from .config import config
from .mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_quick_queries,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
)
from .server_context import _current_user_id, get_client_api_client_http, log
from .server_docs import documentation_cache, initialize_documentation_cache

DOCUMENTATION_CACHE_UNAVAILABLE_MSG = "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
AUTH_HINT_HEADER_TOKEN = "Provide X-MPT-Authorization header with your API token"
OPENAPI_SPEC_LOAD_ERROR = "Failed to load OpenAPI spec"


async def marketplace_docs_list(section: str = None, subsection: str = None, search: str = None, limit: int = 100) -> dict[str, Any]:
    """List documentation resources with optional filters (section, subsection, search)."""
    analytics = get_analytics_logger()
    start_time = time.time()
    try:
        await initialize_documentation_cache()
        if not documentation_cache or not documentation_cache.is_enabled:
            result = {
                "total": 0,
                "resources": [],
                "error": DOCUMENTATION_CACHE_UNAVAILABLE_MSG,
            }
            if analytics and config.analytics_enabled:
                await analytics.log_tool_call(
                    tool_name="marketplace_docs_list",
                    response_time_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error_message="Not initialized",
                )
            return result
        resources = await documentation_cache.list_resources(section=section, subsection=subsection, search=search, limit=limit)
        resources_for_response = []
        for r in resources:
            item = dict(r)
            if r.get("metadata", {}).get("browser_url"):
                item["browser_url"] = r["metadata"]["browser_url"]
            resources_for_response.append(item)
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
            "usage": (
                "Use marketplace_docs_read(uri='docs://path') to read a page. "
                "Prefer showing users the browser_url (public link) when present; "
                "do not show internal uri or id to end users."
            ),
        }
        if len(resources) >= limit:
            result["tip"] = f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
        elif len(resources) > 50:
            result["tip"] = "Consider using 'section' or 'subsection' filters to narrow down results."
        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(
                tool_name="marketplace_docs_list",
                response_time_ms=int((time.time() - start_time) * 1000),
                success=True,
                result_count=result.get("total", 0),
            )
        return result
    except Exception as e:
        if analytics and config.analytics_enabled:
            await analytics.log_tool_call(
                tool_name="marketplace_docs_list",
                response_time_ms=int((time.time() - start_time) * 1000),
                success=False,
                error_message=str(e),
            )
        raise


def register_http_tools(mcp):
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
        try:
            api_client = await get_client_api_client_http()
        except ValueError as e:
            return {"error": str(e), "hint": AUTH_HINT_HEADER_TOKEN}
        api_base_url = api_client.base_url
        log(f"🔍 Using API endpoint: {api_base_url}")
        try:
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
            openapi_spec = await endpoint_registry.get_openapi_spec(api_base_url)
        except Exception as e:
            return {
                "error": f"{OPENAPI_SPEC_LOAD_ERROR} for your endpoint",
                "api_endpoint": api_base_url,
                "details": str(e),
                "hint": f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
            }
        audit_regex = audit_fields_module.get_audit_regex(api_base_url)
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
            audit_regex=audit_regex,
            openapi_spec=openapi_spec,
        )

    @mcp.tool()
    async def marketplace_quick_queries() -> dict[str, Any]:
        return execute_marketplace_quick_queries()

    @mcp.tool()
    async def marketplace_resources() -> dict[str, Any]:
        try:
            api_client = await get_client_api_client_http()
        except ValueError as e:
            return {"error": str(e), "hint": AUTH_HINT_HEADER_TOKEN}
        api_base_url = api_client.base_url
        try:
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as e:
            return {"error": OPENAPI_SPEC_LOAD_ERROR, "details": str(e)}
        user_id = _current_user_id.get()
        return execute_marketplace_resources(
            api_base_url=api_base_url,
            user_id=user_id,
            endpoints_registry=endpoints_registry_data,
        )

    @mcp.tool()
    async def marketplace_resource_info(resource: str) -> dict[str, Any]:
        try:
            api_client = await get_client_api_client_http()
        except ValueError as e:
            return {"error": str(e), "hint": AUTH_HINT_HEADER_TOKEN}
        api_base_url = api_client.base_url
        try:
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as e:
            return {"error": OPENAPI_SPEC_LOAD_ERROR, "details": str(e)}
        return execute_marketplace_resource_info(
            resource=resource,
            endpoints_registry=endpoints_registry_data,
        )

    @mcp.tool()
    async def marketplace_resource_schema(resource: str) -> dict[str, Any]:
        try:
            api_client = await get_client_api_client_http()
        except ValueError as e:
            return {"error": str(e), "hint": AUTH_HINT_HEADER_TOKEN}
        api_base_url = api_client.base_url
        try:
            spec = await endpoint_registry.get_openapi_spec(api_base_url)
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as e:
            return {"error": OPENAPI_SPEC_LOAD_ERROR, "details": str(e)}
        return execute_marketplace_resource_schema(
            resource=resource,
            openapi_spec=spec,
            endpoints_registry=endpoints_registry_data,
        )

    @mcp.tool()
    async def marketplace_audit_fields(resource: str | None = None) -> dict[str, Any]:
        try:
            api_client = await get_client_api_client_http()
        except ValueError as e:
            return {"error": str(e), "hint": AUTH_HINT_HEADER_TOKEN}
        api_base_url = api_client.base_url
        try:
            await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as e:
            return {"error": f"{OPENAPI_SPEC_LOAD_ERROR} for audit fields", "details": str(e), "api_endpoint": api_base_url}
        return audit_fields_module.get_audit_fields(api_base_url, resource)

    @mcp.tool()
    async def marketplace_docs_index() -> dict[str, Any]:
        analytics = get_analytics_logger()
        start_time = time.time()
        try:
            await initialize_documentation_cache()
            if not documentation_cache or not documentation_cache.is_enabled:
                result = {
                    "total_pages": 0,
                    "sections": [],
                    "error": DOCUMENTATION_CACHE_UNAVAILABLE_MSG,
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

    mcp.tool()(marketplace_docs_list)

    @mcp.tool()
    async def marketplace_docs_read(uri: str) -> str:
        analytics = get_analytics_logger()
        start_time = time.time()
        try:
            await initialize_documentation_cache()
            if not documentation_cache or not documentation_cache.is_enabled:
                result = DOCUMENTATION_CACHE_UNAVAILABLE_MSG
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
        analytics = get_analytics_logger()
        start_time = time.time()
        try:
            result = {
                "documentation": {"enabled": False, "total_pages": 0, "cache_info": None},
                "token_validation": {"enabled": False, "cache_stats": None},
            }
            if documentation_cache and documentation_cache.is_enabled:
                cache_info = documentation_cache.get_cache_info()
                result["documentation"] = {
                    "enabled": True,
                    "total_pages": cache_info.get("resource_count", 0),
                    "cache_info": cache_info,
                }
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
