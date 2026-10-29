import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.dependencies import Depends

from mpt_mcp import (
    audit_fields as audit_fields_module,
)
from mpt_mcp import (
    endpoint_registry,
    server_docs,
)
from mpt_mcp.analytics import get_analytics_logger
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.config import config
from mpt_mcp.mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_quick_queries,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
)
from mpt_mcp.token_validator import get_token_cache

logger = logging.getLogger(__name__)

DOCUMENTATION_CACHE_UNAVAILABLE_MSG = (
    "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
)
AUTH_HEADER_HINT = "Provide X-MPT-Authorization header with your API token"
OPENAPI_SPEC_LOAD_ERROR = "Failed to load OpenAPI spec"

MANY_DOCS_RESULTS = 50


async def marketplace_docs_list(
    section: str | None = None,
    subsection: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List documentation resources with optional filters (section, subsection, search)."""
    await server_docs.initialize_documentation_cache()
    dc = server_docs.documentation_cache
    if not dc or not dc.is_enabled:
        return {"total": 0, "resources": [], "error": DOCUMENTATION_CACHE_UNAVAILABLE_MSG}

    resources = await dc.list_resources(
        section=section, subsection=subsection, search=search, limit=limit
    )
    resources_for_response = []
    for resource in resources:
        entry = dict(resource)
        if resource.get("metadata", {}).get("browser_url"):
            entry["browser_url"] = resource["metadata"]["browser_url"]
        resources_for_response.append(entry)
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
        result["tip"] = (
            f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
        )
    elif len(resources) > MANY_DOCS_RESULTS:
        result["tip"] = "Consider using 'section' or 'subsection' filters to narrow down results."

    return result


def register_http_tools(mcp: FastMCP) -> None:
    """Register the Marketplace and documentation tools of the HTTP server."""

    @mcp.tool()
    async def marketplace_query(
        resource: str,
        rql: str = "",
        limit: int | None = None,
        offset: int | None = None,
        select: str | None = None,
        order: str | None = None,
        path_params: dict[str, str] | None = None,
        call_context: CallContext = Depends(get_call_context),
    ) -> dict[str, Any]:
        try:
            api_client = await call_context.create_api_client()
        except ValueError as error:
            return {"error": str(error), "hint": AUTH_HEADER_HINT}
        api_base_url = api_client.base_url
        logger.info("Using API endpoint: %s", api_base_url)
        try:
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
            openapi_spec = await endpoint_registry.get_openapi_spec(api_base_url)
        except Exception as error:
            return {
                "error": f"{OPENAPI_SPEC_LOAD_ERROR} for your endpoint",
                "api_endpoint": api_base_url,
                "details": str(error),
                "hint": f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
            }
        audit_regex = audit_fields_module.get_audit_regex(api_base_url)
        return await execute_marketplace_query(
            resource=resource,
            rql=rql,
            limit=limit,
            offset=offset,
            select=select,
            order=order,
            path_params=path_params,
            api_client=api_client,
            endpoints_registry=endpoints_registry_data,
            analytics_logger=get_analytics_logger(),
            config=config,
            audit_regex=audit_regex,
            openapi_spec=openapi_spec,
        )

    @mcp.tool()
    async def marketplace_quick_queries() -> dict[str, Any]:
        return execute_marketplace_quick_queries()

    @mcp.tool()
    async def marketplace_resources(
        call_context: CallContext = Depends(get_call_context),
    ) -> dict[str, Any]:
        try:
            api_client = await call_context.create_api_client()
        except ValueError as error:
            return {"error": str(error), "hint": AUTH_HEADER_HINT}
        api_base_url = api_client.base_url
        try:
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as error:
            return {"error": OPENAPI_SPEC_LOAD_ERROR, "details": str(error)}
        return execute_marketplace_resources(
            api_base_url=api_base_url,
            user_id=call_context.user_id,
            endpoints_registry=endpoints_registry_data,
        )

    @mcp.tool()
    async def marketplace_resource_info(
        resource: str, call_context: CallContext = Depends(get_call_context)
    ) -> dict[str, Any]:
        try:
            api_client = await call_context.create_api_client()
        except ValueError as error:
            return {"error": str(error), "hint": AUTH_HEADER_HINT}
        api_base_url = api_client.base_url
        try:
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as error:
            return {"error": OPENAPI_SPEC_LOAD_ERROR, "details": str(error)}
        return execute_marketplace_resource_info(
            resource=resource,
            endpoints_registry=endpoints_registry_data,
        )

    @mcp.tool()
    async def marketplace_resource_schema(
        resource: str, call_context: CallContext = Depends(get_call_context)
    ) -> dict[str, Any]:
        try:
            api_client = await call_context.create_api_client()
        except ValueError as error:
            return {"error": str(error), "hint": AUTH_HEADER_HINT}
        api_base_url = api_client.base_url
        try:
            spec = await endpoint_registry.get_openapi_spec(api_base_url)
            endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as error:
            return {"error": OPENAPI_SPEC_LOAD_ERROR, "details": str(error)}
        return execute_marketplace_resource_schema(
            resource=resource,
            openapi_spec=spec,
            endpoints_registry=endpoints_registry_data,
        )

    @mcp.tool()
    async def marketplace_audit_fields(
        resource: str | None = None, call_context: CallContext = Depends(get_call_context)
    ) -> dict[str, Any]:
        try:
            api_client = await call_context.create_api_client()
        except ValueError as error:
            return {"error": str(error), "hint": AUTH_HEADER_HINT}
        api_base_url = api_client.base_url
        try:
            await endpoint_registry.get_endpoints_registry(api_base_url)
        except Exception as error:
            return {
                "error": f"{OPENAPI_SPEC_LOAD_ERROR} for audit fields",
                "details": str(error),
                "api_endpoint": api_base_url,
            }
        return audit_fields_module.get_audit_fields(api_base_url, resource)

    @mcp.tool()
    async def marketplace_docs_index() -> dict[str, Any]:
        await server_docs.initialize_documentation_cache()
        dc = server_docs.documentation_cache
        if not dc or not dc.is_enabled:
            return {"total_pages": 0, "sections": [], "error": DOCUMENTATION_CACHE_UNAVAILABLE_MSG}

        return await dc.get_documentation_index()

    mcp.tool()(marketplace_docs_list)

    @mcp.tool()
    async def marketplace_docs_read(uri: str) -> dict[str, Any]:
        """Read a documentation page by uri (e.g. docs://help-and-support/contact-support).

        Returns a JSON object: {"text": "<markdown content>", "count": 1}.
        Clients should use the "text" field for the document body and "count" (always 1) for
        consistency with other tools.
        """
        await server_docs.initialize_documentation_cache()
        dc = server_docs.documentation_cache
        if not dc or not dc.is_enabled:
            return {"text": DOCUMENTATION_CACHE_UNAVAILABLE_MSG, "count": 0}

        page_content = await dc.get_resource(uri)
        if page_content is None:
            return {
                "text": (
                    f"Documentation page not found: {uri}\n\n"
                    "Use marketplace_docs_list() to see available pages."
                ),
                "count": 0,
            }

        return {"text": page_content, "count": 1}

    # TBD: decide whether this is a debug tool (it only reports cache statistics); if so, tag it
    # "debug" so it is hidden in production
    @mcp.tool()
    async def marketplace_resources_info() -> dict[str, Any]:
        result = {
            "documentation": {"enabled": False, "total_pages": 0, "cache_info": None},
            "token_validation": {"enabled": False, "cache_stats": None},
        }
        dc = server_docs.documentation_cache
        if dc and dc.is_enabled:
            cache_info = dc.get_cache_info()
            result["documentation"] = {
                "enabled": True,
                "total_pages": cache_info.get("resource_count", 0),
                "cache_info": cache_info,
            }
        try:
            token_cache = get_token_cache()
            result["token_validation"] = {
                "enabled": True,
                "cache_stats": token_cache.get_stats(),
                "description": "Token validation cache prevents repeated API calls for "
                "authentication",
            }
        except Exception as e_inner:
            result["token_validation"] = {"enabled": False, "error": str(e_inner)}

        return result
