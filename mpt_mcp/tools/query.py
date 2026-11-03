import difflib
import logging
import re
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP
from fastmcp.dependencies import Depends

from mpt_mcp.analytics import get_analytics_logger
from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.config import config
from mpt_mcp.marketplace import audit_fields as audit_fields_module
from mpt_mcp.marketplace import endpoint_registry
from mpt_mcp.marketplace.audit_fields import FALLBACK_STATIC_REGEX
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.resources import get_response_item_schema
from mpt_mcp.tools.responses import QueryResponse
from mpt_mcp.tools.results import (
    AUTH_HEADER_HINT,
    KEY_META,
    OPENAPI_SPEC_LOAD_ERROR,
    add_page_position,
    fit_result_to_budget,
    tool_error,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mpt_mcp.marketplace.api_client import APIClient

logger = logging.getLogger(__name__)

API_ERROR_TEXT_MAX_LENGTH = 500
RQL_LOG_LENGTH = 80
# Suggestions for an unknown resource: how many, and how close a misspelled name must be (0-1)
SUGGESTION_COUNT = 5
SUGGESTION_SIMILARITY = 0.6
# When present in schema, these fields are always added to select so responses are usable (id,
# status, name).
_ALWAYS_INCLUDE_WHEN_IN_SCHEMA = ("id", "status", "name")


def obfuscate_token_values(data: Any) -> Any:
    """
    Recursively obfuscate 'token' property values in API responses.

    SECURITY: This prevents sensitive token values from being exposed in API responses.
    When querying token-related resources (e.g., accounts.api-tokens), the actual token
    values are replaced with '[REDACTED]' to protect sensitive credentials.

    Args:
        data: The data structure to sanitize (dict, list, or primitive)

    Returns:
        Sanitized data structure with token values obfuscated
    """
    if isinstance(data, dict):
        sanitized = {}
        for key, field_value in data.items():
            if key.lower() == "token" and isinstance(field_value, str) and field_value.strip():
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = obfuscate_token_values(field_value)
        return sanitized

    if isinstance(data, list):
        return [obfuscate_token_values(element) for element in data]

    return data


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


def suggest_resources(resource: str, resources: Iterable[str]) -> list[str]:
    """
    Suggest known resources for an unknown resource name.

    Resources that contain the name, or are contained in it, come first, closest spelling first;
    then resources with a similar spelling, so typos such as catalog.prodcts still get a suggestion.

    Args:
        resource: Unknown resource name, e.g. catalog.prodcts
        resources: Known resource IDs

    Returns:
        Up to SUGGESTION_COUNT resource IDs, best matches first
    """
    resource_lower = resource.lower()
    resources_by_lower = {known.lower(): known for known in resources}
    containing = sorted(
        (
            known_lower
            for known_lower in resources_by_lower
            if resource_lower in known_lower or known_lower in resource_lower
        ),
        key=lambda known_lower: -difflib.SequenceMatcher(None, resource_lower, known_lower).ratio(),
    )
    similar = [
        resources_by_lower[known_lower]
        for known_lower in difflib.get_close_matches(
            resource_lower, resources_by_lower, n=SUGGESTION_COUNT, cutoff=SUGGESTION_SIMILARITY
        )
    ]
    containing_resources = [resources_by_lower[known_lower] for known_lower in containing]
    return list(dict.fromkeys(containing_resources + similar))[:SUGGESTION_COUNT]


def get_allowed_select_fields(
    openapi_spec: dict[str, Any],
    endpoints_registry: dict[str, Any],
    resource: str,
) -> set[str]:
    """Return the top-level fields allowed in select, from the GET response item schema."""
    item_schema = get_response_item_schema(openapi_spec, endpoints_registry, resource)
    return set((item_schema.get("properties") or {}).keys())


def get_used_audit_paths(rql: str, order: str | None, audit_pattern: re.Pattern[str]) -> list[str]:
    """
    List the audit fields a query filters or sorts by, in the order they first appear.

    Args:
        rql: RQL query string
        order: Sort order, such as -audit.created.at
        audit_pattern: Audit fields of the resource, such as audit.created.at

    Returns:
        Audit fields such as audit.created.at, or audit when order sorts by the whole object
    """
    audit_paths = [match.group(0) for match in audit_pattern.finditer(rql or "")]
    for order_part in (order or "").split(","):
        order_field = order_part.strip().lstrip("+-")
        if order_field.lower().startswith("audit"):
            audit_paths.append(order_field)
    return list(dict.fromkeys(audit_paths))


def top_level_field(select_part: str) -> str:
    """
    Return the top-level field a select entry refers to.

    Args:
        select_part: One select entry, e.g. +product.name or -audit

    Returns:
        Field name without its +/- prefix and nested path, e.g. product
    """
    return select_part.lstrip("+-").split(".")[0]


def sanitize_select(
    select: str | None,
    allowed_fields: set[str],
) -> str | None:
    """
    Keep only the allowed top-level fields in select and always include id.

    Status and name are added too when the schema has them.

    Drops any part whose top-level field is not in allowed_fields (if allowed_fields is non-empty).
    """
    if not select or not select.strip():
        return select

    parts = [select_part.strip() for select_part in select.split(",") if select_part.strip()]
    if not parts:
        return select

    has_exclude_all = parts[0] == "-*"
    if has_exclude_all:
        parts = parts[1:]

    kept: list[str] = []
    dropped: list[str] = []
    for part in parts:
        if allowed_fields and top_level_field(part) not in allowed_fields:
            dropped.append(part)
            continue
        kept.append(part)
    if dropped:
        logger.info("Select sanitized: dropped fields not in schema: %s", ", ".join(dropped))

    tops = {top_level_field(select_part) for select_part in kept}
    to_add: list[str] = []
    for field in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA:
        if field in tops:
            continue
        if field == "id" or (allowed_fields and field in allowed_fields):
            to_add.append(field)
            tops.add(field)
    if to_add:
        logger.info("Select: added %s (always included when in schema)", ", ".join(to_add))
    prefix = [
        always_field for always_field in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA if always_field in tops
    ]
    rest = [
        select_part
        for select_part in kept
        if top_level_field(select_part) not in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA
    ]
    kept = prefix + rest

    # Re-add -* at the start if it was present (and convert bare fields to +field when -* is used)
    if has_exclude_all:
        kept = [
            select_part if select_part.startswith(("+", "-")) else f"+{select_part}"
            for select_part in kept
        ]
        selected = ",".join(kept)
        return f"-*,{selected}" if kept else "-*"

    return ",".join(kept)


async def execute_marketplace_query(
    resource: str,
    rql: str,
    limit: int | None,
    offset: int | None,
    select: str | None,
    order: str | None,
    path_params: dict[str, str] | None,
    api_client: APIClient,
    endpoints_registry: dict[str, Any],
    analytics_logger: Any = None,
    config: Any = None,
    audit_regex: re.Pattern[str] | None = None,
    openapi_spec: dict[str, Any] | None = None,
) -> Any:
    """
    Core logic for marketplace_query tool.

    Args:
        resource: The resource to query
        rql: RQL query string
        limit: Maximum items to return
        offset: Items to skip
        select: Fields to include/exclude
        order: Sort order
        path_params: Path parameters dictionary
        api_client: Initialized APIClient instance
        endpoints_registry: Registry of available endpoints
        analytics_logger: Optional analytics logger instance
        config: Optional config object for checking if analytics is enabled
        audit_regex: Audit fields added to select when used (falls back to the static pattern)
        openapi_spec: OpenAPI spec used to validate select fields against the response schema

    Returns:
        API response: usually an object, but some resources return a plain value

    Raises:
        ToolError: The resource is unknown, path parameters are missing or the API call failed
    """
    # Tool-call diagnostics at INFO so they appear in docker logs (log_level=info)
    logger.info(
        "marketplace_query resource=%s rql=%s limit=%s",
        resource,
        (rql or "")[:RQL_LOG_LENGTH],
        limit,
    )
    start_time = time.time()
    query_params = {
        "resource": resource,
        "rql": rql,
        "limit": limit,
        "offset": offset,
        "select": select,
        "order": order,
        "path_params": path_params,
    }

    if resource not in endpoints_registry:
        similar_resources = suggest_resources(resource, endpoints_registry)
        hints: dict[str, Any] = {
            "hint": "Use marketplace_resources() to see all available resources",
            "available_categories": list({
                resource.split(".")[0] for resource in endpoints_registry
            }),
        }

        if similar_resources:
            hints["did_you_mean"] = similar_resources

        raise tool_error(f"Unknown resource: '{resource}'", **hints)

    endpoint_info = endpoints_registry[resource]
    api_path = endpoint_info["path"]

    if path_params:
        for param_name, param_value in path_params.items():
            api_path = api_path.replace(f"{{{param_name}}}", str(param_value))

    remaining_params = re.findall(r"\{(\w+)\}", api_path)
    if remaining_params:
        example_values = {
            "id": "PRD-1234-5678",
            "productId": "PRD-1234-5678",
            "orderId": "ORD-1234-5678-9012",
            "agreementId": "AGR-1234-5678-9012",
            "subscriptionId": "SUB-1234-5678-9012",
            "accountId": "ACC-1234-5678",
            "userId": "USR-1234-5678",
            "lineId": "LIN-1234-5678",
            "assetId": "AST-1234-5678",
        }

        example_dict = {
            missing_param: example_values.get(missing_param, f"<{missing_param}_value>")
            for missing_param in remaining_params
        }

        hint_parts = [
            f"'{missing_param}': '{example_values.get(missing_param, 'value')}'"
            for missing_param in remaining_params
        ]
        hint_dict = ", ".join(hint_parts)
        hint = f"You must provide path_params dictionary. For example: path_params={{{hint_dict}}}"

        required_params = ", ".join(remaining_params)
        raise tool_error(
            f"This resource requires path parameters: {required_params}",
            resource=resource,
            path_template=endpoint_info["path"],
            example=(
                f"marketplace_query(resource='{resource}', path_params={example_dict}, limit=10)"
            ),
            hint=hint,
        )

    # When listing catalog.products without select, default to table-friendly fields to avoid
    # huge payloads and markdown table breaks (URLs, nested objects with "|" in values).
    if resource == "catalog.products" and (not select or not select.strip()):
        select = "-*,+id,+name,+shortDescription"
        logger.info(
            "Default select for catalog.products: -*,+id,+name,+shortDescription (omit select "
            "for full fields)"
        )

    # Select the audit fields used to filter or sort, so the result shows their values
    audit_pattern = FALLBACK_STATIC_REGEX if audit_regex is None else audit_regex
    audit_paths = get_used_audit_paths(rql, order, audit_pattern)

    original_select = select
    auto_added_audit = False

    has_audit_in_select = False
    if select:
        select_parts = [select_part.strip() for select_part in select.split(",")]
        has_audit_in_select = any(
            part in {"audit", "+audit"} or part.startswith(("audit.", "+audit."))
            for part in select_parts
        )

    # Only the fields in use: the whole audit object doubles the size of small items
    if audit_paths and not has_audit_in_select:
        auto_added_audit = True
        audit_select = ",".join(f"+{audit_path}" for audit_path in audit_paths)
        select = f"{select},{audit_select}" if select else audit_select
        logger.info("Auto-added %s to select (audit fields used to filter or sort)", audit_select)

    if select:
        allowed = get_allowed_select_fields(openapi_spec or {}, endpoints_registry, resource)
        select = sanitize_select(select, allowed) or select

    # Cap at 100 to avoid huge responses and context limit errors (platform default is 1000)
    # A path that ends in a parameter returns a single item, so it takes no limit or offset
    if endpoint_info["path"].endswith("}"):
        if limit is not None or offset is not None:
            logger.info("Ignored limit and offset: %s returns a single item", resource)
        limit = None
        offset = None
    elif limit is None:
        limit = 10
        logger.info(
            "Applied default limit=10 (platform default is 1000, too large for most use cases)"
        )
    elif limit == 0:
        # If limit is explicitly set to 0, respect it (might be intentional)
        logger.warning("Limit is 0, keeping as-is (might be intentional)")
    elif limit > 100:
        logger.info("Capped limit %s to 100 (max allowed to avoid context overflow)", limit)
        limit = 100

    query_params = {}
    if rql:
        # The API rejects RQL with spaces after the commas (and(..., ilike(...) with 400
        rql = re.sub(r",\s+", ",", rql)
        query_params["rql"] = rql
    if limit is not None:
        query_params["limit"] = limit
    if offset is not None:
        query_params["offset"] = offset
    if select:
        query_params["select"] = select
    if order:
        query_params["order"] = order

    logger.info("Query: %s", resource)
    logger.info("Path: %s", api_path)
    logger.info("Params: %s", query_params)

    try:
        result = await api_client.get(api_path, query_params=query_params)
        result_count = None
        if isinstance(result, dict) and KEY_META in result:
            result_count = result[KEY_META].get("pagination", {}).get("total")
            logger.info("Result: %s total items", result_count or "?")

        # SECURITY: hide the token values of every API token endpoint, matched by path
        is_token_endpoint = "/accounts/api-tokens" in api_path.lower()
        if is_token_endpoint:
            logger.info("Obfuscating token values in response (security)")
            result = obfuscate_token_values(result)

        if analytics_logger and config and config.analytics_enabled:
            await analytics_logger.log_api_query(
                api_resource=resource,
                api_path=api_path,
                api_method="GET",
                api_status_code=HTTPStatus.OK,
                api_response_time_ms=int((time.time() - start_time) * 1000),
                result_count=result_count,
                rql_filter=rql,
                limit_value=limit,
                offset_value=offset,
                order_by=order,
                select_fields=select,
                tool_name="marketplace_query",
            )

    except Exception as error:
        logger.warning("Error: %s", error)

        error_response: dict[str, Any] = {"resource": resource, "path": api_path}
        response_code = None
        should_retry_without_audit = False

        if isinstance(error, httpx.HTTPStatusError):
            error_response["status_code"] = error.response.status_code
            error_response["request_url"] = str(error.request.url)
            response_code = error.response.status_code
            try:
                error_body = error.response.json()
                error_response["api_error_details"] = error_body

                # If we auto-added audit and got a 400, retry without it
                if response_code == HTTPStatus.BAD_REQUEST and auto_added_audit:
                    logger.info("400 error after auto-adding 'audit' - retrying without it...")
                    should_retry_without_audit = True
                elif response_code == HTTPStatus.BAD_REQUEST and error_body.get("errors"):
                    errors = error_body.get("errors", {})
                    for field, error_list in errors.items():
                        if (
                            isinstance(error_list, list)
                            and any("Unknown expression group" in str(err) for err in error_list)
                            and (
                                "audit" in field.lower()
                                or any("audit" in str(err).lower() for err in error_list)
                            )
                        ):
                            error_response["hint"] = (
                                "The resource does not have this audit field: list its audit "
                                "events with marketplace_audit_fields(resource)"
                            )
                            break
            except Exception:
                error_response["api_error_text"] = error.response.text[:API_ERROR_TEXT_MAX_LENGTH]
                if response_code == HTTPStatus.BAD_REQUEST and auto_added_audit:
                    logger.info("400 error after auto-adding 'audit' - retrying without it...")
                    should_retry_without_audit = True

        if should_retry_without_audit:
            logger.info(
                "Retrying query without auto-added 'audit' (using original select: %s)",
                original_select or "None",
            )
            retry_params = {}
            if rql:
                retry_params["rql"] = rql
            if limit is not None:
                retry_params["limit"] = limit
            if offset is not None:
                retry_params["offset"] = offset
            if original_select:
                retry_params["select"] = original_select
            if order:
                retry_params["order"] = order

            try:
                result = await api_client.get(api_path, query_params=retry_params)
                result_count = None
                if isinstance(result, dict) and KEY_META in result:
                    result_count = result[KEY_META].get("pagination", {}).get("total")
                    logger.info("Retry successful: %s total items", result_count or "?")

                # SECURITY: hide the token values of every API token endpoint, matched by path
                is_token_endpoint = "/accounts/api-tokens" in api_path.lower()
                if is_token_endpoint:
                    logger.info("Obfuscating token values in response (security)")
                    result = obfuscate_token_values(result)

                if analytics_logger and config and config.analytics_enabled:
                    await analytics_logger.log_api_query(
                        api_resource=resource,
                        api_path=api_path,
                        api_method="GET",
                        api_status_code=HTTPStatus.OK,
                        api_response_time_ms=int((time.time() - start_time) * 1000),
                        result_count=result_count,
                        rql_filter=rql,
                        limit_value=limit,
                        offset_value=offset,
                        order_by=order,
                        select_fields=original_select,
                        tool_name="marketplace_query",
                    )

            except Exception as retry_e:
                logger.warning("Retry also failed: %s", retry_e)
                # Fall through to return original error
            else:
                log_query_result(result)

                return result

        if analytics_logger and config and config.analytics_enabled:
            await analytics_logger.log_api_query(
                api_resource=resource,
                api_path=api_path,
                api_method="GET",
                api_status_code=response_code or HTTPStatus.INTERNAL_SERVER_ERROR,
                api_response_time_ms=int((time.time() - start_time) * 1000),
                rql_filter=rql,
                limit_value=limit,
                offset_value=offset,
                order_by=order,
                select_fields=select,
                tool_name="marketplace_query",
            )

        raise tool_error(str(error), **error_response) from error

    log_query_result(result)

    return result


async def marketplace_query(
    resource: str,
    rql: str = "",
    limit: int | None = None,
    offset: int | None = None,
    select: str | None = None,
    order: str | None = None,
    path_params: dict[str, str] | None = None,
    call_context: CallContext = Depends(get_call_context),
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
        limit: Max items to return (default 10, max 100). With many items, return only the
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
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Marketplace API response: a page of items, or a single item
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    logger.info("Using API endpoint: %s", api_base_url)
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
        openapi_spec = await endpoint_registry.get_openapi_spec(api_base_url)
    except Exception as error:
        raise tool_error(
            f"{OPENAPI_SPEC_LOAD_ERROR} for your endpoint",
            api_endpoint=api_base_url,
            details=str(error),
            hint=f"Ensure {api_base_url}/public/v1/openapi.json is accessible",
        ) from error

    audit_regex = audit_fields_module.get_audit_regex(api_base_url)
    result = await execute_marketplace_query(
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
    if not isinstance(result, dict):
        return QueryResponse(result=result)

    return QueryResponse.model_validate(add_page_position(fit_result_to_budget(result)))


def register_query_tools(mcp: FastMCP) -> None:
    """Register the Marketplace query tool."""
    for tool, title, annotations in (
        (marketplace_query, "Query a Marketplace resource", READ_ONLY_REMOTE),
    ):
        mcp.tool(title=title, annotations=annotations)(tool)
