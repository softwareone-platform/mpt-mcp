import logging
from typing import Annotated, Any

from fastmcp.dependencies import Depends
from fastmcp.server.providers import LocalProvider
from pydantic import Field

from mpt_mcp.analytics import AnalyticsLogger, get_analytics_logger
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.dependencies import MarketplaceSpec, get_api_client, get_marketplace_spec
from mpt_mcp.tools.endpoints import get_endpoint
from mpt_mcp.tools.query.params import DEFAULT_LIMIT, QueryParams, build_query
from mpt_mcp.tools.query.paths import fill_path_params
from mpt_mcp.tools.query.request import MarketplaceRequest
from mpt_mcp.tools.responses import QueryResponse
from mpt_mcp.tools.results import KEY_META, add_page_position, fit_result_to_budget

logger = logging.getLogger(__name__)
query_tools = LocalProvider()

# Pages stay small enough for the model's context; the platform default is 1000
MAX_LIMIT = 100
RQL_LOG_LENGTH = 80


@query_tools.tool(title="Query a Marketplace resource", annotations=READ_ONLY_REMOTE)
async def marketplace_query(
    resource: str,
    rql: str = "",
    limit: Annotated[int, Field(ge=0, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Field(ge=0)] | None = None,
    select: str | None = None,
    order: str | None = None,
    path_params: dict[str, str] | None = None,
    api_client: APIClient = Depends(get_api_client),  # noqa: WPS404
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
    analytics_logger: AnalyticsLogger | None = Depends(get_analytics_logger),  # noqa: WPS404
) -> QueryResponse:
    """
    Query the SoftwareOne Marketplace API using Resource Query Language (RQL).

    Supports both simple queries and advanced RQL filtering, sorting, and pagination. See
    documentation at https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language

    Available Resource Categories:
    - Catalog: catalog.products, catalog.items, catalog.listings, catalog.authorizations
    - Commerce: commerce.orders, commerce.agreements, commerce.subscriptions
    - Billing: billing.invoices, billing.statements, billing.journals, billing.ledgers
    - Accounts: accounts.accounts, accounts.buyers, accounts.sellers, accounts.users

    RQL Query Examples:
    - Pagination: limit=10, offset=0
    - Filter: rql=eq(status,Active), limit=20
    - Search: rql=ilike(name,*Microsoft*), limit=50
    - Complex: rql=and(eq(status,Completed),ilike(product.name,*Microsoft*)),
      order=-audit.created.at
    - Sort: order=-audit.created.at or order=+name

    Use marketplace_resources() to see all available resources.

    Args:
        resource: The resource to query (e.g., catalog.products, commerce.orders)
        rql: Advanced RQL query string. Examples: eq(status,Active), ilike(name,*Microsoft*).
            Dates in UTC (YYYY-MM-DDTHH:MM:SS.mmmZ). Use the limit, offset, select and order
            arguments for pagination, fields and sorting, not this string.
        limit: Max items to return (0 to 100, default 10). With many items, return only the
            fields you need (select=-*,+field1,+field2) to avoid huge responses. To page on, pass
            $meta.pagination.next_offset as offset while has_more is true; it also continues a
            page cut to fit one result. A cut page sets $meta.truncated, whose suggested_limit
            fits in one result and lets you fetch the next pages in parallel.
            Ignored for resources that return a single item (path ending in a parameter, e.g.
            *.by_id).
        offset: Number of items to skip for pagination (e.g., 0, 20, 40). For data that changes
            while you page, sort with order=+audit.created.at and filter by date in rql, so new
            items do not shift the pages. Ignored for resources that return a single item.
        select: Fields of each item. The API returns a default set of fields:
            -*,+id,+product.name returns only the listed fields (start with -* to keep
            responses small); +lines adds a field omitted by default (see $meta.omitted) to the
            default set; -price removes one. Nested: +subscriptions (full), +subscriptions.id.
            id, status and name are always included when the resource has them, fields the
            resource does not have are dropped, and the audit fields rql or order use are added
            (+audit.created.at). For catalog.products include vendor as
            +vendor.id,+vendor.name (not +vendor). Without select, catalog.products returns only
            id, status, name and shortDescription.
        order: Sort order (e.g., -audit.created.at for descending, +name for ascending)
        path_params: Path parameters for resources requiring IDs
            Examples: {id: PRD-1234-5678} for catalog.products.by_id
                     {orderId: ORD-1234-5678} for commerce.orders.{orderId}.lines
        api_client: Caller's API client, injected by FastMCP (not a tool argument)
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)
        analytics_logger: Analytics of the process, injected by FastMCP (not a tool argument)

    Returns:
        Marketplace API response: a page of items, or a single item
    """
    # Tool-call diagnostics at INFO so they appear in docker logs (log_level=info)
    logger.info(
        "marketplace_query resource=%s rql=%s limit=%s", resource, rql[:RQL_LOG_LENGTH], limit
    )
    endpoint_path = get_endpoint(resource, spec.endpoints_registry)["path"]
    api_path = fill_path_params(resource, endpoint_path, path_params)
    requested = QueryParams(limit=limit, offset=offset, order=order, rql=rql, select=select)
    query, fallback_query = build_query(resource, endpoint_path, requested, spec)
    request = MarketplaceRequest(resource, api_path, api_client, analytics_logger)
    result = await request.send(query, fallback_query)
    log_query_result(result)
    if not isinstance(result, dict):
        return QueryResponse(result=result)

    return QueryResponse.model_validate(add_page_position(fit_result_to_budget(result)))


def log_query_result(result: Any) -> None:
    """
    Log what marketplace_query returns, so agents can check that $meta and omitted are present.

    Args:
        result: API response; resources that return a plain value are logged as such
    """
    if not isinstance(result, dict):
        logger.info("Returning: %s value", type(result).__name__)
        return

    data = result.get("data")
    data_list = data if isinstance(data, list) else []
    result_meta = result.get(KEY_META)
    meta = result_meta if isinstance(result_meta, dict) else {}
    meta_omitted = meta.get("omitted")
    omitted = meta_omitted if isinstance(meta_omitted, list) else []
    logger.info(
        "Returning: data len=%s, %s=%s, omitted=%s",
        len(data_list),
        KEY_META,
        "yes" if meta else "no",
        omitted or "none",
    )
