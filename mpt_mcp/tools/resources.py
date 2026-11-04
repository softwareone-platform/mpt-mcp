import json
import logging
from typing import Any

from fastmcp.dependencies import Depends
from fastmcp.server.providers import LocalProvider

from mpt_mcp.auth.call_context import CallContext, get_call_context
from mpt_mcp.marketplace import audit_fields as audit_fields_module
from mpt_mcp.marketplace.audit_fields import get_item_schema, resolve_schema
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.dependencies import MarketplaceSpec, get_marketplace_spec
from mpt_mcp.tools.responses import (
    AuditFieldsResponse,
    ResourceInfoResponse,
    ResourceSchemaResponse,
    ResourcesResponse,
)
from mpt_mcp.tools.results import CHARACTER_LIMIT, KEY_META, tool_error

logger = logging.getLogger(__name__)
resource_tools = LocalProvider()

type ResourceEntries = list[dict[str, Any]]

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

    ref = schema.get("$ref")
    if ref is not None:
        ref_path = ref.split("/")
        ref_schema = openapi_spec
        for part in ref_path:
            if part and part != "#":
                ref_schema = ref_schema.get(part, {})
        schema = ref_schema
    resolved = resolve_schema(openapi_spec, get_item_schema(openapi_spec, schema))
    return resolved if isinstance(resolved, dict) else {}


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
            enum_values = param_schema.get("enum")
            if enum_values is not None:
                enum_fields[param_name] = enum_values

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
    categories: dict[str, ResourceEntries] = {}
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
                "Use limit= and offset= for pagination. Max limit 100 (larger fails). When using "
                "limit up to 100, use "
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

    ok_response = responses.get("200")
    if ok_response is not None:
        response_content = ok_response.get("content", {})

        json_content = response_content.get(MEDIA_TYPE_JSON)
        if json_content is not None:
            schema = json_content.get("schema")
            if schema is not None:
                ref = schema.get("$ref")
                if ref is not None:
                    ref_path = ref.split("/")
                    ref_schema = openapi_spec
                    for part in ref_path:
                        if part and part != "#":
                            ref_schema = ref_schema.get(part, {})
                    schema = ref_schema

                schema_info["response_schema"] = schema

                # Fields are those of one item: list responses wrap their items in data
                item_schema = get_response_item_schema(openapi_spec, endpoints_registry, resource)
                item_properties = item_schema.get("properties")
                if item_properties is not None:
                    fields = {}
                    for field_name, declared_schema in item_properties.items():
                        field_schema = resolve_schema(openapi_spec, declared_schema)
                        field_type = field_schema.get("type")
                        if not field_type:
                            field_type = "object" if "properties" in field_schema else "unknown"
                        field_info = {
                            "type": field_type,
                            "description": declared_schema.get("description")
                            or field_schema.get("description", ""),
                        }

                        field_enum = field_schema.get("enum")
                        if field_enum is not None:
                            field_info["enum"] = field_enum
                            field_info["valid_values"] = field_enum

                        field_info.update({
                            key: field_schema[key]
                            for key in ("example", "format")
                            if key in field_schema
                        })

                        nested_properties = field_schema.get("properties")
                        if nested_properties is not None:
                            nested_fields = {}
                            for nested_name, nested_schema in list(nested_properties.items())[:5]:
                                nested_fields[nested_name] = {
                                    "type": nested_schema.get("type", "unknown"),
                                    "description": nested_schema.get("description", ""),
                                }
                            field_info["nested_fields"] = nested_fields

                        fields[field_name] = field_info

                    schema_info["fields"] = fields

                    # Filter hints only for fields RQL compares directly, not objects or arrays
                    scalar_fields = [
                        scalar_name
                        for scalar_name, scalar_info in fields.items()
                        if scalar_info["type"] not in UNFILTERABLE_TYPES
                    ]
                    enum_examples = {
                        enum_name: enum_info["enum"][0]
                        for enum_name, enum_info in fields.items()
                        if "enum" in enum_info
                    }
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
                            f"eq({enum_field},{enum_value})"
                            for enum_field, enum_value in enum_examples.items()
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


@resource_tools.tool(title="List Marketplace resources", annotations=READ_ONLY_REMOTE)
def marketplace_resources(
    category: str | None = None,
    search: str | None = None,
    call_context: CallContext = Depends(get_call_context),  # noqa: WPS404
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
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
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Resources by category
    """
    return ResourcesResponse.model_validate(
        execute_marketplace_resources(
            api_base_url=spec.api_base_url,
            user_id=call_context.user_id,
            endpoints_registry=spec.endpoints_registry,
            category=category,
            search=search,
        )
    )


@resource_tools.tool(title="Describe a Marketplace resource", annotations=READ_ONLY_REMOTE)
def marketplace_resource_info(
    resource: str,
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
) -> ResourceInfoResponse:
    """
    Get detailed information about a specific resource.

    Args:
        resource: The resource identifier (e.g., catalog.products)
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Detailed information about the resource including available parameters
    """
    return ResourceInfoResponse.model_validate(
        execute_marketplace_resource_info(
            resource=resource,
            endpoints_registry=spec.endpoints_registry,
        )
    )


@resource_tools.tool(title="Marketplace resource schema", annotations=READ_ONLY_REMOTE)
def marketplace_resource_schema(
    resource: str,
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
) -> ResourceSchemaResponse:
    """
    Get the response schema of a resource.

    Use marketplace_resource_info for its query and path parameters. For catalog.products use
    select=+vendor.id,+vendor.name when including vendor.

    Args:
        resource: The resource to get the schema for (e.g., catalog.products, commerce.orders)
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Response schema, item fields and RQL filter hints of the resource
    """
    return ResourceSchemaResponse.model_validate(
        execute_marketplace_resource_schema(
            resource=resource,
            openapi_spec=spec.openapi_spec,
            endpoints_registry=spec.endpoints_registry,
        )
    )


@resource_tools.tool(title="Marketplace audit events", annotations=READ_ONLY_REMOTE)
def marketplace_audit_fields(
    resource: str | None = None,
    spec: MarketplaceSpec = Depends(get_marketplace_spec),  # noqa: WPS404
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
        spec: OpenAPI spec of the caller's endpoint, injected by FastMCP (not a tool argument)

    Returns:
        Audit events of the resource, or of every resource
    """
    result = audit_fields_module.get_audit_fields(spec.api_base_url, resource)
    if "error" in result:
        raise tool_error(result.pop("error"), **result)

    return AuditFieldsResponse.model_validate(result)
