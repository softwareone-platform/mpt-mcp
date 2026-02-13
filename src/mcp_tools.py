from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import httpx

from .query_templates import get_query_templates

if TYPE_CHECKING:
    from collections.abc import Callable

    from .api_client import APIClient

logger = logging.getLogger(__name__)

MEDIA_TYPE_JSON = "application/json"
# SoftwareOne API response key for metadata (pagination, omitted fields, etc.)
KEY_META = "$meta"


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
        for key, value in data.items():
            # Obfuscate 'token' property values
            if key.lower() == "token" and isinstance(value, str) and value.strip():
                sanitized[key] = "[REDACTED]"
            else:
                # Recursively sanitize nested structures
                sanitized[key] = obfuscate_token_values(value)
        return sanitized
    elif isinstance(data, list):
        return [obfuscate_token_values(item) for item in data]
    else:
        return data


# ============================================================================
# Select sanitization: ensure id is always included and drop fields not in schema
# ============================================================================


def _get_allowed_select_fields(
    openapi_spec: dict[str, Any],
    endpoints_registry: dict[str, Any],
    resource: str,
) -> set[str]:
    """Return the set of top-level property names allowed in select for this resource (from GET response item schema)."""
    if resource not in endpoints_registry or not openapi_spec:
        return set()
    from .audit_fields import _get_item_schema, _resolve_schema

    endpoint_info = endpoints_registry[resource]
    path = endpoint_info.get("path")
    if not path:
        return set()
    paths = openapi_spec.get("paths") or {}
    if path not in paths or "get" not in paths[path]:
        return set()
    get_op = paths[path]["get"]
    responses = get_op.get("responses") or {}
    content = (responses.get("200") or {}).get("content") or {}
    json_content = content.get(MEDIA_TYPE_JSON) or {}
    schema = json_content.get("schema")
    if not schema or not isinstance(schema, dict):
        return set()
    if "$ref" in schema:
        ref_path = schema["$ref"].split("/")
        ref_schema = openapi_spec
        for part in ref_path:
            if part and part != "#":
                ref_schema = ref_schema.get(part, {})
        schema = ref_schema
    item_schema = _get_item_schema(openapi_spec, schema)
    item_schema = _resolve_schema(openapi_spec, item_schema) if isinstance(item_schema, dict) else item_schema
    if not isinstance(item_schema, dict):
        return set()
    properties = item_schema.get("properties") or {}
    return set(properties.keys())


# When present in schema, these fields are always added to select so responses are usable (id, status, name).
_ALWAYS_INCLUDE_WHEN_IN_SCHEMA = ("id", "status", "name")


def _sanitize_select(
    select: str | None,
    allowed_fields: set[str],
    log_fn: Callable[[str], None] | None,
) -> str | None:
    """
    Ensure select only contains allowed top-level fields and always includes id (and status, name when in schema).
    Drops any part whose top-level field is not in allowed_fields (if allowed_fields is non-empty).
    """
    if not select or not select.strip():
        return select

    def log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    parts = [p.strip() for p in select.split(",") if p.strip()]
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
    for p in parts:
        top = top_level_field(p)
        if allowed_fields and top not in allowed_fields:
            dropped.append(p)
            continue
        kept.append(p)
    if dropped:
        log(f"   💡 Select sanitized: dropped fields not in schema: {', '.join(dropped)}")

    # Always include id; when they exist in schema, also include status and name (in that order)
    tops = {top_level_field(p) for p in kept}
    to_add: list[str] = []
    for field in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA:
        if field in tops:
            continue
        if field == "id" or (allowed_fields and field in allowed_fields):
            to_add.append(field)
            tops.add(field)
    if to_add:
        log(f"   💡 Select: added {', '.join(to_add)} (always included when in schema)")
    # Canonical order: id, status, name first (when present), then the rest
    prefix = [f for f in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA if f in tops]
    rest = [p for p in kept if top_level_field(p) not in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA]
    kept = prefix + rest

    # Re-add -* at the start if it was present (and convert bare fields to +field when -* is used)
    if has_exclude_all:
        # When using -*, fields should use + prefix to explicitly include them
        kept = [p if p.startswith("+") or p.startswith("-") else f"+{p}" for p in kept]
        return "-*," + ",".join(kept) if kept else "-*"
    return ",".join(kept)


# ============================================================================
# Common Tool: marketplace_query
# ============================================================================


async def execute_marketplace_query(
    resource: str,
    rql: str,
    limit: int | None,
    offset: int | None,
    page: int | None,
    select: str | None,
    order: str | None,
    path_params: dict[str, str] | None,
    api_client: APIClient,
    endpoints_registry: dict[str, Any],
    log_fn: Callable[[str], None] | None = None,
    analytics_logger: Any = None,
    config: Any = None,
    audit_regex: re.Pattern[str] | None = None,
    openapi_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Core logic for marketplace_query tool.

    Args:
        resource: The resource to query
        rql: RQL query string
        limit: Maximum items to return
        offset: Items to skip
        page: Page number
        select: Fields to include/exclude
        order: Sort order
        path_params: Path parameters dictionary
        api_client: Initialized APIClient instance
        endpoints_registry: Registry of available endpoints
        log_fn: Optional logging function
        analytics_logger: Optional analytics logger instance
        config: Optional config object for checking if analytics is enabled

    Returns:
        API response or error dictionary
    """
    import time

    # Tool-call diagnostics at INFO so they appear in docker logs (log_level=info)
    logger.info(
        "marketplace_query resource=%s rql=%s limit=%s",
        resource,
        (rql or "")[:80],
        limit,
    )
    start_time = time.time()
    params = {"resource": resource, "rql": rql, "limit": limit, "offset": offset, "page": page, "select": select, "order": order, "path_params": path_params}

    def log(message: str):
        if log_fn:
            log_fn(message)
        # Emit at INFO so tool calls (Query, Params, Result count) show in docker logs
        logger.info("%s", message)

    try:
        # Check if resource exists
        if resource not in endpoints_registry:
            # Find similar resources to suggest
            similar_resources = []
            resource_lower = resource.lower()
            for r in endpoints_registry:
                if resource_lower in r.lower() or r.lower() in resource_lower:
                    similar_resources.append(r)

            error_response = {
                "error": f"Unknown resource: '{resource}'",
                "hint": "Use marketplace_resources() to see all available resources",
                "available_categories": list({r.split(".")[0] for r in endpoints_registry}),
            }

            if similar_resources[:5]:  # Show up to 5 suggestions
                error_response["did_you_mean"] = similar_resources[:5]

            return error_response

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

            example_dict = {p: example_values.get(p, f"<{p}_value>") for p in remaining_params}

            # Build hint string
            hint_parts = [f"'{p}': '{example_values.get(p, 'value')}'" for p in remaining_params]
            hint = f"You must provide path_params dictionary. For example: path_params={{{', '.join(hint_parts)}}}"

            return {
                "error": f"This resource requires path parameters: {', '.join(remaining_params)}",
                "resource": resource,
                "path_template": endpoint_info["path"],
                "example": f"marketplace_query(resource='{resource}', path_params={example_dict}, limit=10)",
                "hint": hint,
            }

        # Auto-detect audit field usage in RQL and ensure audit is selected
        # The API requires select=audit when filtering/sorting by audit fields
        # Use dynamic regex from spec-derived cache if provided, else fallback (includes failed)
        from .audit_fields import FALLBACK_STATIC_REGEX

        _audit_pattern = audit_regex if audit_regex is not None else FALLBACK_STATIC_REGEX
        uses_audit_fields = bool(rql and _audit_pattern.search(rql))
        uses_audit_in_order = bool(order and "audit" in order.lower())

        # Store original select value for potential retry
        original_select = select
        auto_added_audit = False

        # Check if audit is already in select
        has_audit_in_select = False
        if select:
            # Parse select string (e.g., "+id,+name,audit" or "+audit.created.at")
            select_parts = [s.strip() for s in select.split(",")]
            has_audit_in_select = any(part == "audit" or part == "+audit" or part.startswith("audit.") or part.startswith("+audit.") for part in select_parts)

        # Auto-add audit to select if needed
        if (uses_audit_fields or uses_audit_in_order) and not has_audit_in_select:
            auto_added_audit = True
            if select:
                # Append audit to existing select
                select = f"{select},audit"
            else:
                # Create new select with audit
                select = "audit"
            log("   💡 Auto-added 'audit' to select (required for audit field filtering/sorting)")

        # Sanitize select: drop fields not in resource schema and ensure id is always included
        if select:
            allowed = _get_allowed_select_fields(openapi_spec or {}, endpoints_registry, resource)
            select = _sanitize_select(select, allowed, log) or select

        # Apply default limit of 10 if not explicitly specified
        # Cap at 100 to avoid huge responses and context limit errors (platform default is 1000)
        if limit is None:
            limit = 10
            log("   💡 Applied default limit=10 (platform default is 1000, too large for most use cases)")
        elif limit == 0:
            # If limit is explicitly set to 0, respect it (might be intentional)
            log("   ⚠️ Limit is 0, keeping as-is (might be intentional)")
        elif limit > 100:
            log(f"   💡 Capped limit {limit} to 100 (max allowed to avoid context overflow)")
            limit = 100

        # Build query parameters
        params = {}
        if rql:
            # Sanitize RQL: remove spaces after commas in function calls (e.g. "and(..., ilike(..." -> "and(...,ilike(...")
            # This prevents 400 errors from the API which is strict about RQL syntax
            rql = re.sub(r",\s+", ",", rql)
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
            result_count = None
            if KEY_META in result:
                result_count = result[KEY_META].get("pagination", {}).get("total")
                log(f"   ✅ Result: {result_count or '?'} total items")

            # SECURITY: Obfuscate token values if querying API token endpoints
            # Check the actual API path to catch /public/v1/accounts/api-tokens and /public/v1/accounts/api-tokens/{id}
            # This ensures we catch all token-related endpoints regardless of resource name
            is_token_endpoint = "/accounts/api-tokens" in api_path.lower()
            if is_token_endpoint:
                log("   🔒 Obfuscating token values in response (security)")
                result = obfuscate_token_values(result)

            # Log successful API query
            if analytics_logger and config and config.analytics_enabled:
                await analytics_logger.log_api_query(
                    api_resource=resource,
                    api_path=api_path,
                    api_method="GET",
                    api_status_code=200,
                    api_response_time_ms=int((time.time() - start_time) * 1000),
                    result_count=result_count,
                    rql_filter=rql,
                    limit_value=limit,
                    offset_value=offset,
                    order_by=order,
                    select_fields=select,
                    tool_name="marketplace_query",
                )

            # Log what we return so agent-side can verify $meta/omitted are present
            data_list = result.get("data") if isinstance(result.get("data"), list) else []
            meta = result.get(KEY_META) if isinstance(result.get(KEY_META), dict) else {}
            omitted = meta.get("omitted") if isinstance(meta.get("omitted"), list) else []
            log(f"   📤 Returning: data len={len(data_list)}, {KEY_META}={'yes' if meta else 'no'}, omitted={omitted if omitted else 'none'}")

            return result
        except Exception as e:
            log(f"   ❌ Error: {e}")

            error_response = {"error": str(e), "resource": resource, "path": api_path}
            response_code = None
            should_retry_without_audit = False

            # If it's an HTTP error, try to include response body
            if isinstance(e, httpx.HTTPStatusError):
                error_response["status_code"] = e.response.status_code
                error_response["request_url"] = str(e.request.url)
                response_code = e.response.status_code
                try:
                    # Try to parse error response body
                    error_body = e.response.json()
                    error_response["api_error_details"] = error_body

                    # If we auto-added audit and got a 400, retry without it
                    if response_code == 400 and auto_added_audit:
                        log("   🔄 400 error after auto-adding 'audit' - retrying without it...")
                        should_retry_without_audit = True
                    # Check for audit field filtering errors and provide helpful hint
                    elif response_code == 400 and error_body.get("errors"):
                        errors = error_body.get("errors", {})
                        # Check if any error mentions "Unknown expression group" for audit fields
                        for field, error_list in errors.items():
                            if isinstance(error_list, list) and any("Unknown expression group" in str(err) for err in error_list):
                                if "audit" in field.lower() or any("audit" in str(err).lower() for err in error_list):
                                    error_response["hint"] = (
                                        "When filtering or sorting by audit fields (e.g., audit.created.at), "
                                        "you must include 'audit' in the select parameter. "
                                        "Example: select='audit' or select='+id,+name,audit'"
                                    )
                                    break
                except Exception:
                    # If not JSON, include raw text
                    error_response["api_error_text"] = e.response.text[:500]  # Limit to 500 chars
                    # If we auto-added audit and got a 400, still try retry
                    if response_code == 400 and auto_added_audit:
                        log("   🔄 400 error after auto-adding 'audit' - retrying without it...")
                        should_retry_without_audit = True

            # Retry without auto-added audit if we got a 400
            if should_retry_without_audit:
                log(f"   🔄 Retrying query without auto-added 'audit' (using original select: {original_select or 'None'})")
                retry_params = {}
                if rql:
                    retry_params["rql"] = rql
                if limit is not None:
                    retry_params["limit"] = limit
                if offset is not None:
                    retry_params["offset"] = offset
                if page is not None:
                    retry_params["page"] = page
                if original_select:
                    retry_params["select"] = original_select
                if order:
                    retry_params["order"] = order

                try:
                    result = await api_client.get(api_path, params=retry_params)
                    result_count = None
                    if KEY_META in result:
                        result_count = result[KEY_META].get("pagination", {}).get("total")
                        log(f"   ✅ Retry successful: {result_count or '?'} total items")

                    # SECURITY: Obfuscate token values if querying API token endpoints
                    # Check the actual API path to catch /public/v1/accounts/api-tokens and /public/v1/accounts/api-tokens/{id}
                    # This ensures we catch all token-related endpoints regardless of resource name
                    is_token_endpoint = "/accounts/api-tokens" in api_path.lower()
                    if is_token_endpoint:
                        log("   🔒 Obfuscating token values in response (security)")
                        result = obfuscate_token_values(result)

                    # Log successful API query after retry
                    if analytics_logger and config and config.analytics_enabled:
                        await analytics_logger.log_api_query(
                            api_resource=resource,
                            api_path=api_path,
                            api_method="GET",
                            api_status_code=200,
                            api_response_time_ms=int((time.time() - start_time) * 1000),
                            result_count=result_count,
                            rql_filter=rql,
                            limit_value=limit,
                            offset_value=offset,
                            order_by=order,
                            select_fields=original_select,
                            tool_name="marketplace_query",
                        )

                    # Log what we return so agent-side can verify $meta/omitted are present
                    data_list = result.get("data") if isinstance(result.get("data"), list) else []
                    meta = result.get(KEY_META) if isinstance(result.get(KEY_META), dict) else {}
                    omitted = meta.get("omitted") if isinstance(meta.get("omitted"), list) else []
                    log(f"   📤 Returning: data len={len(data_list)}, {KEY_META}={'yes' if meta else 'no'}, omitted={omitted if omitted else 'none'}")

                    return result
                except Exception as retry_e:
                    log(f"   ❌ Retry also failed: {retry_e}")
                    # Fall through to return original error

            # Log failed API query
            if analytics_logger and config and config.analytics_enabled:
                await analytics_logger.log_api_query(
                    api_resource=resource,
                    api_path=api_path,
                    api_method="GET",
                    api_status_code=response_code or 500,
                    api_response_time_ms=int((time.time() - start_time) * 1000),
                    rql_filter=rql,
                    limit_value=limit,
                    offset_value=offset,
                    order_by=order,
                    select_fields=select,
                    tool_name="marketplace_query",
                )

            return error_response
    except Exception as outer_e:
        # Log catastrophic failures at tool call level (shouldn't happen, but just in case)
        if analytics_logger and config and config.analytics_enabled:
            await analytics_logger.log_tool_call(
                tool_name="marketplace_query",
                response_time_ms=int((time.time() - start_time) * 1000),
                success=False,
                error_type="exception",
                error_message=str(outer_e),
            )
        raise


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


def execute_marketplace_resources(
    api_base_url: str,
    user_id: str | None,
    endpoints_registry: dict[str, Any],
) -> dict[str, Any]:
    """
    Core logic for marketplace_resources tool.

    Args:
        api_base_url: The API base URL
        user_id: Current user ID (for display)
        endpoints_registry: Registry of available endpoints

    Returns:
        Detailed resource catalog organized by category
    """
    # Build enhanced categories with more metadata
    categories = {}
    for resource_name, endpoint_info in endpoints_registry.items():
        category = resource_name.split(".")[0]
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

    return {
        "api_endpoint": api_base_url,
        "user": user_id or "unknown",
        "total_resources": len(endpoints_registry),
        "categories": categories,
        "usage": {
            "query_resource": "Use marketplace_query(resource='category.resource', ...) to query any resource",
            "get_schema": "Use marketplace_resource_schema(resource='...') to see full field list and types",
            "get_details": "Use marketplace_resource_info(resource='...') for parameter details",
        },
        "tips": {
            "filtering": "Use RQL for complex filters: eq(field,value), ilike(name,*keyword*), and(condition1,condition2)",
            "pagination": (
                "Use limit= and offset= for pagination. Max limit 100 (capped). When using limit up to 100, use "
                "select= with only the fields you need (from marketplace_resource_schema); "
                "otherwise the response may cause a context limit error."
            ),
            "sorting": "Use order= parameter: order=-created (descending), order=+name (ascending)",
            "field_selection": (
                "Use select=: select=+id,+name,+status or select=-metadata. Many fields omitted by default "
                f"({KEY_META}.omitted). Use select=+field for lines, parameters, subscriptions. Nested: "
                "+subscriptions (full), +subscriptions.id (ids only), +subscriptions.id,+subscriptions.name. "
                "RQL filter fields must exist on the resource—use marketplace_resource_schema(resource) to check."
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
    """
    if resource not in endpoints_registry:
        return {
            "error": f"Unknown resource: {resource}",
            "hint": "Use marketplace_resources() to see all available resources",
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
                "required": param.get("required", True),
            }

        # Extract enum values for query parameters
        if "enum" in param_schema and param_in == "query":
            enum_fields[param_name] = param_schema["enum"]

    # Find related resources (children and siblings)
    related_resources = {"children": [], "parent": None, "siblings": []}

    resource_path = endpoint_info["path"]
    for other_resource, other_info in endpoints_registry.items():
        if other_resource == resource:
            continue

        other_path = other_info["path"]

        # Child resources: start with current path and go deeper
        if other_path.startswith(resource_path + "/") and other_resource.startswith(resource + "."):
            related_resources["children"].append({"resource": other_resource, "summary": other_info["summary"]})

        # Parent resource: current path extends parent
        if resource_path.startswith(other_path + "/") and resource.startswith(other_resource + "."):
            # Only set if this is the immediate parent (not grandparent)
            if not related_resources["parent"] or len(other_path) > len(related_resources["parent"]["path"]):
                related_resources["parent"] = {
                    "resource": other_resource,
                    "summary": other_info["summary"],
                    "path": other_path,
                }

        # Sibling resources: same parent category
        resource_parts = resource.split(".")
        other_parts = other_resource.split(".")
        if len(resource_parts) >= 2 and len(other_parts) >= 2:
            if resource_parts[0] == other_parts[0] and resource_parts[1] == other_parts[1]:
                # Same subcategory, not self
                if len(resource_parts) == len(other_parts) and other_resource != resource:
                    related_resources["siblings"].append({"resource": other_resource, "summary": other_info["summary"]})

    # Limit siblings to top 5 most relevant
    if len(related_resources["siblings"]) > 5:
        related_resources["siblings"] = related_resources["siblings"][:5]

    # Limit children to top 10 most common
    if len(related_resources["children"]) > 10:
        related_resources["children"] = related_resources["children"][:10]

    # Build query examples
    examples = [f"marketplace_query(resource='{resource}', limit=10)"]

    # Add example with enum filter if available
    if enum_fields:
        first_enum_field = list(enum_fields.keys())[0]
        first_enum_value = enum_fields[first_enum_field][0]
        examples.append(f"marketplace_query(resource='{resource}', rql='eq({first_enum_field},{first_enum_value})', limit=10)")

    # Add example with path params if needed
    if path_params_info:
        example_params = {k: f"<{k}_value>" for k in path_params_info}
        examples.append(f"marketplace_query(resource='{resource}', path_params={example_params}, select='+id,+name')")

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
            "select": (f"Fields to include/exclude. Use select=+field for omitted fields (see {KEY_META}.omitted). Example: select=+lines,+parameters."),
            "order": "Sort order (e.g., -created for descending, +name for ascending)",
            "path_params": "Dictionary of path parameters (e.g., {id: PRD-1234-5678})",
        },
        "omitted_fields_note": (f"Many resources omit fields by default. Check {KEY_META}.omitted in responses; use select=+field to include them."),
        "example_queries": examples,
    }

    # Add enum fields if any found
    if enum_fields:
        result["enum_fields"] = enum_fields
        result["filtering_tips"] = f"Filter by {', '.join(enum_fields.keys())} using RQL: eq({list(enum_fields.keys())[0]},<value>)"

    # Add path parameters info if any found
    if path_params_info:
        result["path_parameters"] = path_params_info
        param_list = ", ".join([f"{k}=<value>" for k in path_params_info])
        result["path_params_required"] = f"This resource requires path parameters: {param_list}"

    # Add related resources if found
    if related_resources["parent"] or related_resources["children"] or related_resources["siblings"]:
        result["related_resources"] = {}
        if related_resources["parent"]:
            result["related_resources"]["parent"] = related_resources["parent"]
        if related_resources["children"]:
            result["related_resources"]["children"] = related_resources["children"]
        if related_resources["siblings"]:
            result["related_resources"]["similar"] = related_resources["siblings"]

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
    """
    if resource not in endpoints_registry:
        return {
            "error": f"Unknown resource: {resource}",
            "hint": "Use marketplace_resources() to see all available resources",
            "available_categories": list({r.split(".")[0] for r in endpoints_registry}),
        }

    endpoint_info = endpoints_registry[resource]
    path = endpoint_info["path"]

    # Find the endpoint in the OpenAPI spec
    paths = openapi_spec.get("paths", {})
    if path not in paths:
        return {"error": f"Path {path} not found in OpenAPI spec", "resource": resource}

    path_item = paths[path]
    if "get" not in path_item:
        return {"error": f"GET operation not found for {path}", "resource": resource}

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

        if MEDIA_TYPE_JSON in content:
            json_content = content[MEDIA_TYPE_JSON]
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

                # Extract field information from properties
                if "properties" in schema:
                    fields = {}
                    for field_name, field_schema in schema["properties"].items():
                        field_info = {
                            "type": field_schema.get("type", "unknown"),
                            "description": field_schema.get("description", ""),
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
                                    "description": nested_schema.get("description", ""),
                                }
                            field_info["nested_fields"] = nested_fields

                        fields[field_name] = field_info

                    schema_info["fields"] = fields

                    # Add filtering hints
                    schema_info["filtering_hints"] = {
                        "simple_filters": [f"eq({f},value)" for f in list(fields.keys())[:5]],
                        "search_fields": [f"ilike({f},*keyword*)" for f, info in list(fields.items())[:3] if info.get("type") == "string"],
                        "enum_filters": [f"eq({f},{info['enum'][0]})" for f, info in fields.items() if "enum" in info][:3],
                    }

    # Add common query patterns
    schema_info["common_queries"] = {
        "basic": f"{resource}?limit=10",
        "with_filters": f"{resource}?eq(status,Active)&limit=20",
        "with_sorting": f"{resource}?order=-id&limit=10",
        "full_example": f"{resource}?eq(status,Active)&order=-id&select=+id,+name,+status&limit=50",
    }

    return schema_info
