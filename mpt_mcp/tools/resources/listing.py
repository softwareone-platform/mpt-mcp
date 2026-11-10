import json
from types import MappingProxyType
from typing import Any

from mpt_mcp.tools.responses import ResourceEntry, ResourcesResponse
from mpt_mcp.tools.results import CHARACTER_LIMIT, KEY_META, tool_error
from mpt_mcp.tools.spec import MarketplaceSpec

MAX_FILTERABLE_FIELDS = 5
COMPACT_CATEGORY_NOTE = (
    "The category is too long for one result, so only names and summaries are listed: "
    "use marketplace_resource_info(resource) for a resource's details, or narrow the "
    "list with search."
)
COMPACT_LIST_NOTE = (
    "The list is too long for one result, so only names are listed: narrow it with "
    "category or search to get the summaries."
)
RESOURCES_USAGE = MappingProxyType({
    "list_category": "Use marketplace_resources(category='...') for the descriptions, "
    "paths and filterable fields of a category's resources",
    "query_resource": "Use marketplace_query(resource='category.resource', ...) to query "
    "any resource",
    "get_schema": "Use marketplace_resource_schema(resource='...') to see full field "
    "list and types",
    "get_details": "Use marketplace_resource_info(resource='...') for parameter details",
})
RESOURCES_TIPS = MappingProxyType({
    "filtering": "Use RQL for complex filters: eq(field,value), ilike(name,*keyword*), "
    "and(condition1,condition2)",
    "pagination": (
        "Use limit= and offset= for pagination. Max limit 100 (larger fails). When using "
        "limit up to 100, use "
        "select= with only the fields you need (from marketplace_resource_schema); "
        "otherwise the response may cause a context limit error."
    ),
    "sorting": (
        "Use order= parameter: order=-audit.created.at (descending), order=+name (ascending)"
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
})


def list_resources(  # noqa: WPS210
    spec: MarketplaceSpec,
    *,
    user_id: str | None,
    category: str | None,
    search: str | None,
) -> ResourcesResponse:
    """
    List the resources of the registry, grouped by category.

    Without a category, every resource has only its name and summary; a category adds the
    details of its resources. A list longer than CHARACTER_LIMIT is shortened, with a note that
    says so: names only without a category, names and summaries with one.

    Args:
        spec: OpenAPI spec of the caller's endpoint, with its registry
        user_id: Current user ID (for display)
        category: Only resources of this category, with their details
        search: Only resources whose name or summary contains this text (case-insensitive)

    Returns:
        Resources by category

    Raises:
        ToolError: The category does not exist
    """
    all_categories = spec.get_categories()
    if category is not None and category not in all_categories:
        raise tool_error(f"Unknown category: {category}", available_categories=all_categories)

    categories: dict[str, list[ResourceEntry]] = {}
    for resource_name, endpoint_info in spec.endpoints_registry.items():
        if matches_filters(resource_name, endpoint_info, category=category, search=search):
            categories.setdefault(resource_name.split(".")[0], []).append(
                describe_resource(resource_name, endpoint_info, detailed=category is not None)
            )

    resources_response = ResourcesResponse(
        api_endpoint=spec.api_base_url,
        user=user_id or "unknown",
        total_resources=sum(len(entries) for entries in categories.values()),
        categories=categories,
        usage=dict(RESOURCES_USAGE),
        tips=dict(RESOURCES_TIPS),
    )
    response_size = len(json.dumps(resources_response.model_dump(by_alias=True), default=str))
    if response_size > CHARACTER_LIMIT:
        return compact_resources(resources_response, has_category=category is not None)

    return resources_response


def compact_resources(
    resources_response: ResourcesResponse, *, has_category: bool
) -> ResourcesResponse:
    """
    Keep only the names of the listed resources, and their summaries when a category was asked.

    Args:
        resources_response: marketplace_resources result that does not fit in one result
        has_category: Whether the list is one category's resources, with their details

    Returns:
        The same list with fewer fields per resource, and a note that says how to narrow it
    """
    compact_categories = {
        category_name: [
            ResourceEntry(
                resource=resource_entry.resource,
                summary=resource_entry.summary if has_category else None,
            )
            for resource_entry in resource_entries
        ]
        for category_name, resource_entries in resources_response.categories.items()
    }
    return resources_response.model_copy(
        update={
            "categories": compact_categories,
            "note": COMPACT_CATEGORY_NOTE if has_category else COMPACT_LIST_NOTE,
        }
    )


def describe_resource(
    resource_name: str, endpoint_info: dict[str, Any], *, detailed: bool
) -> ResourceEntry:
    """
    Describe a resource of the list: its name and summary, and its details when detailed.

    Args:
        resource_name: Resource name
        endpoint_info: Registry entry of the resource
        detailed: Add the path, description, filterable and enum fields

    Returns:
        Resource entry of the list
    """
    if not detailed:
        return ResourceEntry(resource=resource_name, summary=endpoint_info["summary"])

    query_params = [
        param_spec
        for param_spec in endpoint_info.get("parameters", [])
        if param_spec.get("in") == "query" and param_spec.get("name", "")
    ]
    enum_fields = {
        param_spec["name"]: param_spec.get("schema", {})["enum"]
        for param_spec in query_params
        if param_spec.get("schema", {}).get("enum") is not None
    }
    filterable_fields = [param_spec["name"] for param_spec in query_params]
    return ResourceEntry(
        resource=resource_name,
        summary=endpoint_info["summary"],
        path=endpoint_info["path"],
        description=endpoint_info.get("description") or None,
        filterable_fields=filterable_fields[:MAX_FILTERABLE_FIELDS] or None,
        enum_fields=enum_fields or None,
    )


def matches_filters(
    resource_name: str,
    endpoint_info: dict[str, Any],
    *,
    category: str | None,
    search: str | None,
) -> bool:
    """
    Tell whether a resource is in the category and its name or summary contains search.

    Args:
        resource_name: Resource name
        endpoint_info: Registry entry of the resource
        category: Category to keep, or None for every category
        search: Text the name or summary must contain (case-insensitive), or None

    Returns:
        True when the resource passes both filters
    """
    if category is not None and resource_name.partition(".")[0] != category:
        return False

    if not search:
        return True

    return search.lower() in f"{resource_name} {endpoint_info['summary']}".lower()
