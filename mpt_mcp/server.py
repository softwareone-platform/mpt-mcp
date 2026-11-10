from typing import Literal

from fastmcp import FastMCP

from mpt_mcp.analytics import AnalyticsMiddleware, analytics_lifespan
from mpt_mcp.config import config
from mpt_mcp.documentation.lifespan import documentation_lifespan, documentation_store_lifespan
from mpt_mcp.documentation.server import documentation_provider
from mpt_mcp.prompts import marketplace_prompts
from mpt_mcp.resources import openapi_resources
from mpt_mcp.runtime.middleware import RequestContextMiddleware
from mpt_mcp.tools.debug import DEBUG_TAG, debug_tools
from mpt_mcp.tools.query import query_tools
from mpt_mcp.tools.resources import resource_tools
from mpt_mcp.tools.spec_store import spec_lifespan

SERVER_NAME = "softwareone-marketplace"
type Transport = Literal["http", "stdio"]
SERVER_INSTRUCTIONS = """\
Read-only access to the SoftwareOne Marketplace API, with the caller's credentials, and to the \
Marketplace documentation.

To answer questions about Marketplace data:
1. Find the resource with marketplace_resources: narrow it with search (for example order) or \
category (for example commerce), since the full list has hundreds of resources. Resources are \
named after their API path, for example commerce.orders or catalog.products.by_id.
2. Check its parameters and enum values with marketplace_resource_info, its response fields \
with marketplace_resource_schema, and its audit events (audit.<event>.at and \
audit.<event>.by) with marketplace_audit_fields when filtering by date or user.
3. Query it with marketplace_query: filter with rql, sort with order, and paginate with limit \
and offset (10 items by default, 100 at most). Every item comes with a default set of fields: \
to return only the fields you need, start select with -* (select=-*,+id,+status).

RQL filters: eq(field,value) and ne for exact values, ilike(field,*text*) for a case-insensitive \
search, gt, ge, lt and le for numbers and dates, and and(...), or(...) and not(...) to combine \
them, with no spaces after the commas. Nested fields use dots (product.id). Dates are UTC: \
ge(audit.created.at,2026-01-31T00:00:00.000Z).

To answer questions about how the Marketplace works, browse marketplace_docs_index or search \
with marketplace_docs_list, then read a page with marketplace_docs_read. Show users the \
browser_url of a page, not its docs:// uri.
"""


def create_mcp_server(*, transport: Transport) -> FastMCP:
    """
    Create the MCP server with every tool, resource and prompt, served by both transports.

    Args:
        transport: http also loads the documentation at startup and records analytics events;
            stdio loads the documentation on the first documentation call

    Returns:
        MCP server, with the debug tools disabled unless DEBUG=true
    """
    # RequestContextMiddleware runs first so analytics and tool logs carry the caller's log prefix
    if transport == "http":
        mcp = FastMCP(
            SERVER_NAME,
            instructions=SERVER_INSTRUCTIONS,
            lifespan=documentation_lifespan | analytics_lifespan | spec_lifespan,
            middleware=[RequestContextMiddleware(), AnalyticsMiddleware()],
        )
    else:
        mcp = FastMCP(
            SERVER_NAME,
            instructions=SERVER_INSTRUCTIONS,
            lifespan=documentation_store_lifespan | spec_lifespan,
            middleware=[RequestContextMiddleware()],
        )
    for provider in (
        query_tools,
        resource_tools,
        debug_tools,
        documentation_provider,
        openapi_resources,
        marketplace_prompts,
    ):
        mcp.add_provider(provider)
    if not config.debug:
        mcp.disable(tags={DEBUG_TAG})
    return mcp
