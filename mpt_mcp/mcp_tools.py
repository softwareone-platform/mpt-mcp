from __future__ import annotations

import difflib
import json
import logging
import re
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp.exceptions import ToolError

from mpt_mcp.audit_fields import FALLBACK_STATIC_REGEX, get_item_schema, resolve_schema
from mpt_mcp.query_templates import get_query_templates

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mpt_mcp.api_client import APIClient

logger = logging.getLogger(__name__)

MEDIA_TYPE_JSON = "application/json"
UNFILTERABLE_TYPES = frozenset(("array", "object", "unknown"))
# SoftwareOne API response key for metadata (pagination, omitted fields, etc.)
KEY_META = "$meta"

API_ERROR_TEXT_MAX_LENGTH = 500

# Query parameters listed per resource by marketplace_resources(category=...)
MAX_FILTERABLE_FIELDS = 5

RQL_LOG_LENGTH = 80

# Suggestions for an unknown resource: how many, and how close a misspelled name must be (0-1)
SUGGESTION_COUNT = 5
SUGGESTION_SIMILARITY = 0.6


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
            # Obfuscate 'token' property values
            if key.lower() == "token" and isinstance(field_value, str) and field_value.strip():
                sanitized[key] = "[REDACTED]"
            else:
                # Recursively sanitize nested structures
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


def tool_error(message: str, **details: Any) -> ToolError:
    """
    Build a tool error that carries its hints, so MCP clients mark the result as an error.

    Args:
        message: What failed
        details: Hints for the caller, such as an example or similar resources

    Returns:
        Tool error with the message followed by the hints as JSON
    """
    if not details:
        return ToolError(message)

    return ToolError(f"{message}\n{json.dumps(details, default=str)}")


# ============================================================================
# Select sanitization: ensure id is always included and drop fields not in schema
# ============================================================================


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


def get_response_item_schema(
    openapi_spec: dict[str, Any],
    endpoints_registry: dict[str, Any],
    resource: str,
) -> dict[str, Any]:
    """
    Return the schema of one item of a resource's GET response.

    List responses wrap their items as {"$meta": ..., "data": [items]}; the item schema is the
    one inside data, and single-item responses are the item themselves.

    Args:
        openapi_spec: The full OpenAPI specification
        endpoints_registry: Registry of available endpoints
        resource: The resource to get the item schema for

    Returns:
        Item schema with its $ref and allOf resolved, or {} when the spec does not describe it
    """
    if resource not in endpoints_registry or not openapi_spec:
        return {}

    endpoint_info = endpoints_registry[resource]
    path = endpoint_info.get("path")
    if not path:
        return {}

    paths = openapi_spec.get("paths") or {}
    if path not in paths or "get" not in paths[path]:
        return {}

    get_op = paths[path]["get"]
    responses = get_op.get("responses") or {}
    response_content = (responses.get("200") or {}).get("content") or {}
    json_content = response_content.get(MEDIA_TYPE_JSON) or {}
    schema = json_content.get("schema")
    if not schema or not isinstance(schema, dict):
        return {}

    if "$ref" in schema:
        ref_path = schema["$ref"].split("/")
        ref_schema = openapi_spec
        for part in ref_path:
            if part and part != "#":
                ref_schema = ref_schema.get(part, {})
        schema = ref_schema
    item_schema = get_item_schema(openapi_spec, schema)
    item_schema = (
        resolve_schema(openapi_spec, item_schema) if isinstance(item_schema, dict) else item_schema
    )
    return item_schema if isinstance(item_schema, dict) else {}


# When present in schema, these fields are always added to select so responses are usable (id,
# status, name).
_ALWAYS_INCLUDE_WHEN_IN_SCHEMA = ("id", "status", "name")


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

    # Preserve -* (exclude-all directive) at the start if present
    has_exclude_all = parts[0] == "-*"
    if has_exclude_all:
        parts = parts[1:]  # Process remaining fields

    # Top-level field name for validation (strip +/-, take segment before first dot)
    def top_level_field(part: str) -> str:
        name = part.lstrip("+-")
        return name.split(".")[0] if "." in name else name

    kept: list[str] = []
    dropped: list[str] = []
    for select_part in parts:
        top = top_level_field(select_part)
        if allowed_fields and top not in allowed_fields:
            dropped.append(select_part)
            continue
        kept.append(select_part)
    if dropped:
        logger.info("Select sanitized: dropped fields not in schema: %s", ", ".join(dropped))

    # Always include id; when they exist in schema, also include status and name (in that order)
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
    # Canonical order: id, status, name first (when present), then the rest
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
        # When using -*, fields should use + prefix to explicitly include them
        kept = [
            select_part if select_part.startswith(("+", "-")) else f"+{select_part}"
            for select_part in kept
        ]
        selected = ",".join(kept)
        return f"-*,{selected}" if kept else "-*"

    return ",".join(kept)


# ============================================================================
# Common Tool: marketplace_query
# ============================================================================


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

    # Check if resource exists
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

    # Replace path parameters (e.g., {id}, {productId}, etc.)
    if path_params:
        for param_name, param_value in path_params.items():
            # Replace {param_name} in the path
            api_path = api_path.replace(f"{{{param_name}}}", str(param_value))

    # Check if there are still unresolved path parameters
    remaining_params = re.findall(r"\{(\w+)\}", api_path)
    if remaining_params:
        # Create example path_params dict with realistic examples
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

        # Build hint string
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
    # Use dynamic regex from spec-derived cache if provided, else fallback (includes failed)
    audit_pattern = audit_regex if audit_regex is not None else FALLBACK_STATIC_REGEX
    audit_paths = get_used_audit_paths(rql, order, audit_pattern)

    # Store original select value for potential retry
    original_select = select
    auto_added_audit = False

    # Check if audit is already in select
    has_audit_in_select = False
    if select:
        # Parse select string (e.g., "+id,+name,audit" or "+audit.created.at")
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

    # Sanitize select: drop fields not in resource schema and ensure id is always included
    if select:
        allowed = get_allowed_select_fields(openapi_spec or {}, endpoints_registry, resource)
        select = sanitize_select(select, allowed) or select

    # Apply default limit of 10 if not explicitly specified
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

    # Build query parameters
    query_params = {}
    if rql:
        # Sanitize RQL: remove spaces after commas in function calls (e.g. "and(..., ilike(..." ->
        # "and(...,ilike(...")
        # This prevents 400 errors from the API which is strict about RQL syntax
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

        # SECURITY: Obfuscate token values if querying API token endpoints
        # Check the actual API path to catch /public/v1/accounts/api-tokens and
        # /public/v1/accounts/api-tokens/{id}
        # This ensures we catch all token-related endpoints regardless of resource name
        is_token_endpoint = "/accounts/api-tokens" in api_path.lower()
        if is_token_endpoint:
            logger.info("Obfuscating token values in response (security)")
            result = obfuscate_token_values(result)

        # Log successful API query
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

        log_query_result(result)

        return result
    except Exception as error:
        logger.warning("Error: %s", error)

        error_response: dict[str, Any] = {"resource": resource, "path": api_path}
        response_code = None
        should_retry_without_audit = False

        # If it's an HTTP error, try to include response body
        if isinstance(error, httpx.HTTPStatusError):
            error_response["status_code"] = error.response.status_code
            error_response["request_url"] = str(error.request.url)
            response_code = error.response.status_code
            try:
                # Try to parse error response body
                error_body = error.response.json()
                error_response["api_error_details"] = error_body

                # If we auto-added audit and got a 400, retry without it
                if response_code == HTTPStatus.BAD_REQUEST and auto_added_audit:
                    logger.info("400 error after auto-adding 'audit' - retrying without it...")
                    should_retry_without_audit = True
                # Check for audit field filtering errors and provide helpful hint
                elif response_code == HTTPStatus.BAD_REQUEST and error_body.get("errors"):
                    errors = error_body.get("errors", {})
                    # Check if any error mentions "Unknown expression group" for audit fields
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
                # If not JSON, include raw text
                error_response["api_error_text"] = error.response.text[:API_ERROR_TEXT_MAX_LENGTH]
                # If we auto-added audit and got a 400, still try retry
                if response_code == HTTPStatus.BAD_REQUEST and auto_added_audit:
                    logger.info("400 error after auto-adding 'audit' - retrying without it...")
                    should_retry_without_audit = True

        # Retry without auto-added audit if we got a 400
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

                # SECURITY: Obfuscate token values if querying API token endpoints
                # Check the actual API path to catch /public/v1/accounts/api-tokens and
                # /public/v1/accounts/api-tokens/{id}
                # This ensures we catch all token-related endpoints regardless of resource name
                is_token_endpoint = "/accounts/api-tokens" in api_path.lower()
                if is_token_endpoint:
                    logger.info("Obfuscating token values in response (security)")
                    result = obfuscate_token_values(result)

                # Log successful API query after retry
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

                log_query_result(result)

                return result
            except Exception as retry_e:
                logger.warning("Retry also failed: %s", retry_e)
                # Fall through to return original error

        # Log failed API query
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


# ============================================================================
# Common Tool: marketplace_quick_queries
# ============================================================================


def execute_marketplace_quick_queries() -> dict[str, Any]:
    """
    Core logic for marketplace_quick_queries tool.

    Returns:
        Dictionary of query templates organized by category
    """
    return get_query_templates()


# ============================================================================
# Common Tool: marketplace_resources
# ============================================================================


def describe_resource(resource_name: str, endpoint_info: dict[str, Any]) -> dict[str, Any]:
    """
    Describe a resource for marketplace_resources: its path, description and query parameters.

    Args:
        resource_name: Resource name
        endpoint_info: Registry entry of the resource

    Returns:
        Resource entry with its name, summary, path, description, filterable and enum fields
    """
    resource_entry = {
        "resource": resource_name,
        "summary": endpoint_info["summary"],
        "path": endpoint_info["path"],
    }
    if endpoint_info.get("description"):
        resource_entry["description"] = endpoint_info["description"]

    filterable_fields = []
    enum_fields = {}
    for param_spec in endpoint_info.get("parameters", []):
        param_name = param_spec.get("name", "")
        if param_spec.get("in") == "query" and param_name:
            filterable_fields.append(param_name)
            param_schema = param_spec.get("schema", {})
            if "enum" in param_schema:
                enum_fields[param_name] = param_schema["enum"]

    if filterable_fields:
        resource_entry["filterable_fields"] = filterable_fields[:MAX_FILTERABLE_FIELDS]
    if enum_fields:
        resource_entry["enum_fields"] = enum_fields

    return resource_entry


def execute_marketplace_resources(
    api_base_url: str,
    user_id: str | None,
    endpoints_registry: dict[str, Any],
    category: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """
    Core logic for marketplace_resources tool.

    Without a category, every resource has only its name and summary, so the whole catalog fits
    in a tool response; a category adds the details of its resources.

    Args:
        api_base_url: The API base URL
        user_id: Current user ID (for display)
        endpoints_registry: Registry of available endpoints
        category: Only resources of this category, with their details
        search: Only resources whose name or summary contains this text (case-insensitive)

    Returns:
        Resource catalog organized by category

    Raises:
        ToolError: The category does not exist
    """
    all_categories = sorted({resource_name.split(".")[0] for resource_name in endpoints_registry})
    if category is not None and category not in all_categories:
        raise tool_error(f"Unknown category: {category}", available_categories=all_categories)

    search_lower = search.lower() if search else None
    categories: dict[str, list[dict[str, Any]]] = {}
    for resource_name, endpoint_info in endpoints_registry.items():
        resource_category = resource_name.split(".")[0]
        if category is not None and resource_category != category:
            continue

        summary = endpoint_info["summary"]
        if search_lower and search_lower not in f"{resource_name} {summary}".lower():
            continue

        if category is None:
            resource_entry = {"resource": resource_name, "summary": summary}
        else:
            resource_entry = describe_resource(resource_name, endpoint_info)
        categories.setdefault(resource_category, []).append(resource_entry)

    total_resources = sum(len(entries) for entries in categories.values())

    return {
        "api_endpoint": api_base_url,
        "user": user_id or "unknown",
        "total_resources": total_resources,
        "categories": categories,
        "usage": {
            "list_category": "Use marketplace_resources(category='...') for the descriptions, "
            "paths and filterable fields of a category's resources",
            "query_resource": "Use marketplace_query(resource='category.resource', ...) to query "
            "any resource",
            "get_schema": "Use marketplace_resource_schema(resource='...') to see full field "
            "list and types",
            "get_details": "Use marketplace_resource_info(resource='...') for parameter details",
        },
        "tips": {
            "filtering": "Use RQL for complex filters: eq(field,value), ilike(name,*keyword*), "
            "and(condition1,condition2)",
            "pagination": (
                "Use limit= and offset= for pagination. Max limit 100 (capped). When using limit "
                "up to 100, use "
                "select= with only the fields you need (from marketplace_resource_schema); "
                "otherwise the response may cause a context limit error."
            ),
            "sorting": (
                "Use order= parameter: order=-audit.created.at (descending), order=+name "
                "(ascending)"
            ),
            "field_selection": (
                "Start select with -* to return only the listed fields: select=-*,+id,+status. "
                "Without -*, +field adds a field to the default ones and -field removes one. "
                f"Many fields are omitted by default ({KEY_META}.omitted): add them with "
                "select=+lines, +parameters or +subscriptions. "
                "Nested: "
                "+subscriptions (full), +subscriptions.id (ids only), "
                "+subscriptions.id,+subscriptions.name. "
                "For catalog.products when including vendor use select=+vendor.id,+vendor.name "
                "(not +vendor). "
                "RQL filter fields must exist on the resource—use "
                "marketplace_resource_schema(resource) to check."
            ),
        },
    }


# ============================================================================
# Common Tool: marketplace_resource_info
# ============================================================================


def execute_marketplace_resource_info(
    resource: str,
    endpoints_registry: dict[str, Any],
) -> dict[str, Any]:
    """
    Core logic for marketplace_resource_info tool.

    Args:
        resource: The resource to get information about
        endpoints_registry: Registry of available endpoints

    Returns:
        Detailed resource information

    Raises:
        ToolError: The resource is unknown
    """
    if resource not in endpoints_registry:
        raise tool_error(
            f"Unknown resource: {resource}",
            hint="Use marketplace_resources() to see all available resources",
        )

    endpoint_info = endpoints_registry[resource]

    # Extract enum values from parameters
    enum_fields = {}
    path_params_info = {}

    for param_spec in endpoint_info.get("parameters", []):
        param_name = param_spec.get("name")
        param_in = param_spec.get("in")
        param_schema = param_spec.get("schema", {})

        # Track path parameters
        if param_in == "path":
            path_params_info[param_name] = {
                "type": param_schema.get("type", "string"),
                "description": param_spec.get("description", f"Path parameter: {param_name}"),
                "required": param_spec.get("required", True),
            }

        # Extract enum values for query parameters
        if "enum" in param_schema and param_in == "query":
            enum_fields[param_name] = param_schema["enum"]

    # Find related resources (children and siblings)
    children: list[dict[str, Any]] = []
    parent: dict[str, Any] | None = None
    siblings: list[dict[str, Any]] = []

    resource_path = endpoint_info["path"]
    for other_resource, other_info in endpoints_registry.items():
        if other_resource == resource:
            continue

        other_path = other_info["path"]

        # Child resources: start with current path and go deeper
        if other_path.startswith(f"{resource_path}/") and other_resource.startswith(f"{resource}."):
            children.append({
                "resource": other_resource,
                "summary": other_info["summary"],
            })

        # Parent resource: current path extends parent; keep only the immediate parent
        is_parent = resource_path.startswith(f"{other_path}/") and resource.startswith(
            f"{other_resource}."
        )
        is_closer_parent = not parent or len(other_path) > len(parent["path"])
        if is_parent and is_closer_parent:
            parent = {
                "resource": other_resource,
                "summary": other_info["summary"],
                "path": other_path,
            }

        # Sibling resources: same parent category
        resource_parts = resource.split(".")
        other_parts = other_resource.split(".")
        # Same subcategory and depth, not self
        same_subcategory = (
            len(resource_parts) >= 2
            and len(other_parts) >= 2
            and resource_parts[:2] == other_parts[:2]
        )
        if (
            same_subcategory
            and len(resource_parts) == len(other_parts)
            and other_resource != resource
        ):
            siblings.append({
                "resource": other_resource,
                "summary": other_info["summary"],
            })

    # Limit siblings to top 5 most relevant and children to top 10 most common
    siblings = siblings[:5]
    children = children[:10]

    # Build query examples
    examples = [f"marketplace_query(resource='{resource}', limit=10)"]

    # Add example with enum filter if available
    if enum_fields:
        first_enum_field = next(iter(enum_fields.keys()))
        first_enum_value = enum_fields[first_enum_field][0]
        examples.append(
            f"marketplace_query(resource='{resource}', "
            f"rql='eq({first_enum_field},{first_enum_value})', limit=10)"
        )

    # Add example with path params if needed
    if path_params_info:
        example_params = {param_name: f"<{param_name}_value>" for param_name in path_params_info}
        examples.append(
            f"marketplace_query(resource='{resource}', path_params={example_params}, "
            "select='-*,+id,+name')"
        )

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
            "select": (
                "Fields of each item. select=-*,+id,+name returns only the listed fields; "
                "select=+lines,+parameters adds fields omitted by default (see "
                f"{KEY_META}.omitted) to the default ones."
            ),
            "order": "Sort order (e.g., -audit.created.at for descending, +name for ascending)",
            "path_params": "Dictionary of path parameters (e.g., {id: PRD-1234-5678})",
        },
        "omitted_fields_note": (
            f"Many resources omit fields by default. Check {KEY_META}.omitted in responses; use "
            "select=+field to include them."
        ),
        "example_queries": examples,
    }

    # Add enum fields if any found
    if enum_fields:
        result["enum_fields"] = enum_fields
        enum_names = list(enum_fields.keys())
        enum_list = ", ".join(enum_names)
        first_enum = enum_names[0]
        result["filtering_tips"] = f"Filter by {enum_list} using RQL: eq({first_enum},<value>)"

    # Add path parameters info if any found
    if path_params_info:
        result["path_parameters"] = path_params_info
        param_list = ", ".join([f"{param_name}=<value>" for param_name in path_params_info])
        result["path_params_required"] = f"This resource requires path parameters: {param_list}"

    # Add related resources if found
    related_resources: dict[str, Any] = {}
    if parent:
        related_resources["parent"] = parent
    if children:
        related_resources["children"] = children
    if siblings:
        related_resources["similar"] = siblings
    if related_resources:
        result["related_resources"] = related_resources

    return result


# ============================================================================
# Common Tool: marketplace_resource_schema
# ============================================================================


def execute_marketplace_resource_schema(
    resource: str,
    openapi_spec: dict[str, Any],
    endpoints_registry: dict[str, Any],
) -> dict[str, Any]:
    """
    Core logic for marketplace_resource_schema tool.

    Args:
        resource: The resource to get the schema for
        openapi_spec: The full OpenAPI specification
        endpoints_registry: Registry of available endpoints

    Returns:
        Complete JSON schema with field types and descriptions

    Raises:
        ToolError: The resource is unknown or its GET operation is not in the OpenAPI spec
    """
    if resource not in endpoints_registry:
        raise tool_error(
            f"Unknown resource: {resource}",
            hint="Use marketplace_resources() to see all available resources",
            available_categories=list({resource.split(".")[0] for resource in endpoints_registry}),
        )

    endpoint_info = endpoints_registry[resource]
    path = endpoint_info["path"]

    # Find the endpoint in the OpenAPI spec
    paths = openapi_spec.get("paths", {})
    if path not in paths:
        raise tool_error(f"Path {path} not found in OpenAPI spec", resource=resource)

    path_item = paths[path]
    if "get" not in path_item:
        raise tool_error(f"GET operation not found for {path}", resource=resource)

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
        ok_response = responses["200"]
        response_content = ok_response.get("content", {})

        if MEDIA_TYPE_JSON in response_content:
            json_content = response_content[MEDIA_TYPE_JSON]
            if "schema" in json_content:
                schema = json_content["schema"]

                # If schema references components, try to resolve it
                if "$ref" in schema:
                    ref_path = schema["$ref"].split("/")
                    ref_schema = openapi_spec
                    for part in ref_path:
                        if part and part != "#":
                            ref_schema = ref_schema.get(part, {})
                    schema = ref_schema

                schema_info["response_schema"] = schema

                # Fields are those of one item: list responses wrap their items in data
                item_schema = get_response_item_schema(openapi_spec, endpoints_registry, resource)
                if "properties" in item_schema:
                    fields = {}
                    for field_name, declared_schema in item_schema["properties"].items():
                        field_schema = resolve_schema(openapi_spec, declared_schema)
                        field_type = field_schema.get("type")
                        if not field_type:
                            field_type = "object" if "properties" in field_schema else "unknown"
                        field_info = {
                            "type": field_type,
                            "description": declared_schema.get("description")
                            or field_schema.get("description", ""),
                        }

                        if "enum" in field_schema:
                            field_info["enum"] = field_schema["enum"]
                            field_info["valid_values"] = field_schema["enum"]

                        if "example" in field_schema:
                            field_info["example"] = field_schema["example"]

                        if "format" in field_schema:
                            field_info["format"] = field_schema["format"]

                        # For nested objects, show structure
                        if "properties" in field_schema:
                            nested_fields = {}
                            for nested_name, nested_schema in list(
                                field_schema["properties"].items()
                            )[:5]:
                                nested_fields[nested_name] = {
                                    "type": nested_schema.get("type", "unknown"),
                                    "description": nested_schema.get("description", ""),
                                }
                            field_info["nested_fields"] = nested_fields

                        fields[field_name] = field_info

                    schema_info["fields"] = fields

                    # Filter hints only for fields RQL compares directly, not objects or arrays
                    scalar_fields = [
                        field_name
                        for field_name, field_info in fields.items()
                        if field_info["type"] not in UNFILTERABLE_TYPES
                    ]
                    schema_info["filtering_hints"] = {
                        "simple_filters": [
                            f"eq({filter_field},value)" for filter_field in scalar_fields[:5]
                        ],
                        "search_fields": [
                            f"ilike({filter_field},*keyword*)"
                            for filter_field in scalar_fields
                            if fields[filter_field]["type"] == "string"
                        ][:3],
                        "enum_filters": [
                            f"eq({filter_field},{filter_info['enum'][0]})"
                            for filter_field, filter_info in fields.items()
                            if "enum" in filter_info
                        ][:3],
                    }

    # Add common query patterns
    schema_info["common_queries"] = {
        "basic": f"{resource}?limit=10",
        "with_filters": f"{resource}?eq(status,Active)&limit=20",
        "with_sorting": f"{resource}?order=-id&limit=10",
        "full_example": (
            f"{resource}?eq(status,Active)&order=-id&select=-*,+id,+name,+status&limit=50"
        ),
    }

    return schema_info
