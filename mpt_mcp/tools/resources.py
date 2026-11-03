import json
import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.dependencies import Depends

from mpt_mcp import (
    audit_fields as audit_fields_module,
)
from mpt_mcp import endpoint_registry
from mpt_mcp.audit_fields import get_item_schema, resolve_schema
from mpt_mcp.call_context import CallContext, get_call_context
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.responses import (
    AuditFieldsResponse,
    ResourceInfoResponse,
    ResourceSchemaResponse,
    ResourcesResponse,
)
from mpt_mcp.tools.results import (
    AUTH_HEADER_HINT,
    CHARACTER_LIMIT,
    KEY_META,
    OPENAPI_SPEC_LOAD_ERROR,
    tool_error,
)

logger = logging.getLogger(__name__)

MEDIA_TYPE_JSON = "application/json"
UNFILTERABLE_TYPES = frozenset(("array", "object", "unknown"))
MAX_FILTERABLE_FIELDS = 5


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


def compact_resources(resources_response: dict[str, Any], *, has_category: bool) -> None:
    """
    Keep only the names of the listed resources, and their summaries when a category was asked.

    Args:
        resources_response: marketplace_resources result, changed in place
        has_category: Whether the list is one category's resources, with their details
    """
    kept_keys = ("resource", "summary") if has_category else ("resource",)
    resources_response["categories"] = {
        category_name: [
            {key: resource_entry[key] for key in kept_keys} for resource_entry in resource_entries
        ]
        for category_name, resource_entries in resources_response["categories"].items()
    }
    if has_category:
        resources_response["note"] = (
            "The category is too long for one result, so only names and summaries are listed: "
            "use marketplace_resource_info(resource) for a resource's details, or narrow the "
            "list with search."
        )
    else:
        resources_response["note"] = (
            "The list is too long for one result, so only names are listed: narrow it with "
            "category or search to get the summaries."
        )


def execute_marketplace_resources(
    api_base_url: str,
    user_id: str | None,
    endpoints_registry: dict[str, Any],
    category: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """
    Core logic for marketplace_resources tool.

    Without a category, every resource has only its name and summary; a category adds the
    details of its resources. A list longer than CHARACTER_LIMIT is shortened, with a note that
    says so: names only without a category, names and summaries with one.

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

    resources_response = {
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
    if len(json.dumps(resources_response, default=str)) > CHARACTER_LIMIT:
        compact_resources(resources_response, has_category=category is not None)
    return resources_response


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

    enum_fields = {}
    path_params_info = {}

    for param_spec in endpoint_info.get("parameters", []):
        param_name = param_spec.get("name")
        param_in = param_spec.get("in")
        param_schema = param_spec.get("schema", {})

        if param_in == "path":
            path_params_info[param_name] = {
                "type": param_schema.get("type", "string"),
                "description": param_spec.get("description", f"Path parameter: {param_name}"),
                "required": param_spec.get("required", True),
            }

        if "enum" in param_schema and param_in == "query":
            enum_fields[param_name] = param_schema["enum"]

    children: list[dict[str, Any]] = []
    parent: dict[str, Any] | None = None
    siblings: list[dict[str, Any]] = []

    resource_path = endpoint_info["path"]
    for other_resource, other_info in endpoints_registry.items():
        if other_resource == resource:
            continue

        other_path = other_info["path"]

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

        resource_parts = resource.split(".")
        other_parts = other_resource.split(".")
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

    siblings = siblings[:5]
    children = children[:10]

    examples = [f"marketplace_query(resource='{resource}', limit=10)"]

    if enum_fields:
        first_enum_field = next(iter(enum_fields.keys()))
        first_enum_value = enum_fields[first_enum_field][0]
        examples.append(
            f"marketplace_query(resource='{resource}', "
            f"rql='eq({first_enum_field},{first_enum_value})', limit=10)"
        )

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

    if enum_fields:
        result["enum_fields"] = enum_fields
        enum_names = list(enum_fields.keys())
        enum_list = ", ".join(enum_names)
        first_enum = enum_names[0]
        result["filtering_tips"] = f"Filter by {enum_list} using RQL: eq({first_enum},<value>)"

    if path_params_info:
        result["path_parameters"] = path_params_info
        param_list = ", ".join([f"{param_name}=<value>" for param_name in path_params_info])
        result["path_params_required"] = f"This resource requires path parameters: {param_list}"

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

    paths = openapi_spec.get("paths", {})
    if path not in paths:
        raise tool_error(f"Path {path} not found in OpenAPI spec", resource=resource)

    path_item = paths[path]
    if "get" not in path_item:
        raise tool_error(f"GET operation not found for {path}", resource=resource)

    get_op = path_item["get"]

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

    schema_info["common_queries"] = {
        "basic": f"{resource}?limit=10",
        "with_filters": f"{resource}?eq(status,Active)&limit=20",
        "with_sorting": f"{resource}?order=-id&limit=10",
        "full_example": (
            f"{resource}?eq(status,Active)&order=-id&select=-*,+id,+name,+status&limit=50"
        ),
    }

    return schema_info


async def marketplace_resources(
    category: str | None = None,
    search: str | None = None,
    call_context: CallContext = Depends(get_call_context),
) -> ResourcesResponse:
    """
    List the queryable API resources, grouped by category.

    Without a category, each resource comes with its name and summary only. Pass a category to
    get the path, description and filterable fields of its resources. A list too long for one
    result is shortened to fewer fields, and note says how to narrow it.

    Args:
        category: Only resources of this category, with their details (e.g. commerce, catalog)
        search: Only resources whose name or summary contains this text (e.g. order)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Resources by category
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(OPENAPI_SPEC_LOAD_ERROR, details=str(error)) from error

    return ResourcesResponse.model_validate(
        execute_marketplace_resources(
            api_base_url=api_base_url,
            user_id=call_context.user_id,
            endpoints_registry=endpoints_registry_data,
            category=category,
            search=search,
        )
    )


async def marketplace_resource_info(
    resource: str, call_context: CallContext = Depends(get_call_context)
) -> ResourceInfoResponse:
    """
    Get detailed information about a specific resource.

    Args:
        resource: The resource identifier (e.g., catalog.products)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Detailed information about the resource including available parameters
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(OPENAPI_SPEC_LOAD_ERROR, details=str(error)) from error

    return ResourceInfoResponse.model_validate(
        execute_marketplace_resource_info(
            resource=resource,
            endpoints_registry=endpoints_registry_data,
        )
    )


async def marketplace_resource_schema(
    resource: str, call_context: CallContext = Depends(get_call_context)
) -> ResourceSchemaResponse:
    """
    Get the response schema of a resource.

    Use marketplace_resource_info for its query and path parameters. For catalog.products use
    select=+vendor.id,+vendor.name when including vendor.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Response schema, item fields and RQL filter hints of the resource
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        spec = await endpoint_registry.get_openapi_spec(api_base_url)
        endpoints_registry_data = await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(OPENAPI_SPEC_LOAD_ERROR, details=str(error)) from error

    return ResourceSchemaResponse.model_validate(
        execute_marketplace_resource_schema(
            resource=resource,
            openapi_spec=spec,
            endpoints_registry=endpoints_registry_data,
        )
    )


async def marketplace_audit_fields(
    resource: str | None = None, call_context: CallContext = Depends(get_call_context)
) -> AuditFieldsResponse:
    """
    Get audit event names per resource for filtering by "when" something happened.

    Derived from the OpenAPI spec. Returns event names (e.g. created, updated, failed); paths are
    always audit.<event>.at (when) and audit.<event>.by (who). Use for queries like "orders failed
    starting when" (audit.failed.at) or "agreements created after X" (audit.created.at).
    marketplace_query adds audit to select when rql or order use these fields.

    Args:
        resource: Optional. If provided, returns events for this resource only
                  (e.g. commerce.orders). If omitted, returns all resources.
        call_context: Caller's credentials, injected by FastMCP (not a tool argument)

    Returns:
        Audit events of the resource, or of every resource
    """
    try:
        api_client = await call_context.create_api_client()
    except ValueError as error:
        raise tool_error(str(error), hint=AUTH_HEADER_HINT) from error

    api_base_url = api_client.base_url
    try:
        await endpoint_registry.get_endpoints_registry(api_base_url)
    except Exception as error:
        raise tool_error(
            f"{OPENAPI_SPEC_LOAD_ERROR} for audit fields",
            details=str(error),
            api_endpoint=api_base_url,
        ) from error

    result = audit_fields_module.get_audit_fields(api_base_url, resource)
    if "error" in result:
        raise tool_error(result.pop("error"), **result)

    return AuditFieldsResponse.model_validate(result)


def register_resource_tools(mcp: FastMCP) -> None:
    """Register the tools that describe the Marketplace resources."""
    for tool, title, annotations in (
        (marketplace_resources, "List Marketplace resources", READ_ONLY_REMOTE),
        (marketplace_resource_info, "Describe a Marketplace resource", READ_ONLY_REMOTE),
        (marketplace_resource_schema, "Marketplace resource schema", READ_ONLY_REMOTE),
        (marketplace_audit_fields, "Marketplace audit events", READ_ONLY_REMOTE),
    ):
        mcp.tool(title=title, annotations=annotations)(tool)
