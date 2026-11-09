from types import MappingProxyType
from typing import Any

from mpt_mcp.tools.responses import (
    PathParameter,
    RelatedResource,
    RelatedResources,
    ResourceInfoResponse,
)
from mpt_mcp.tools.results import KEY_META
from mpt_mcp.tools.spec import MarketplaceSpec

MAX_CHILDREN = 10
MAX_SIMILAR = 5
# Resources are similar when they share their first two name segments, e.g. commerce.orders
SIMILAR_PREFIX_PARTS = 2
COMMON_PARAMETERS = MappingProxyType({
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
})
OMITTED_FIELDS_NOTE = (
    f"Many resources omit fields by default. Check {KEY_META}.omitted in responses; use "
    "select=+field to include them."
)


def describe_resource_info(resource: str, spec: MarketplaceSpec) -> ResourceInfoResponse:
    """
    Describe a resource: its parameters, enum values, related resources and example queries.

    Args:
        resource: Resource name
        spec: OpenAPI spec of the endpoint, with its registry

    Returns:
        Detailed resource information

    Raises:
        ToolError: The resource is unknown
    """
    endpoint_info = spec.get_endpoint(resource)
    enum_fields = get_query_enum_fields(endpoint_info)
    path_parameters = get_path_parameters(endpoint_info)
    return ResourceInfoResponse(
        resource=resource,
        path=endpoint_info["path"],
        summary=endpoint_info["summary"],
        description=endpoint_info.get("description", ""),
        parameters=endpoint_info["parameters"],
        response_schema=endpoint_info.get("response", {}),
        common_parameters=dict(COMMON_PARAMETERS),
        omitted_fields_note=OMITTED_FIELDS_NOTE,
        example_queries=build_example_queries(resource, enum_fields, path_parameters),
        enum_fields=enum_fields or None,
        filtering_tips=build_filtering_tips(enum_fields),
        path_parameters=path_parameters or None,
        path_params_required=build_path_params_required(path_parameters),
        related_resources=find_related_resources(resource, endpoint_info, spec.endpoints_registry),
    )


def build_example_queries(
    resource: str,
    enum_fields: dict[str, list[Any]],
    path_parameters: dict[str, PathParameter],
) -> list[str]:
    """
    Build marketplace_query calls for a resource: a plain one, and with a filter or path params.

    Args:
        resource: Resource name
        enum_fields: Query parameters with a fixed set of values, and those values
        path_parameters: Path parameters of the resource

    Returns:
        marketplace_query calls, the plain one first
    """
    examples = [f"marketplace_query(resource='{resource}', limit=10)"]
    if enum_fields:
        first_enum_field = next(iter(enum_fields))
        first_enum_value = enum_fields[first_enum_field][0]
        examples.append(
            f"marketplace_query(resource='{resource}', "
            f"rql='eq({first_enum_field},{first_enum_value})', limit=10)"
        )
    if path_parameters:
        example_params = {param_name: f"<{param_name}_value>" for param_name in path_parameters}
        examples.append(
            f"marketplace_query(resource='{resource}', path_params={example_params}, "
            "select='-*,+id,+name')"
        )
    return examples


def build_filtering_tips(enum_fields: dict[str, list[Any]]) -> str | None:
    """Say how to filter by the enum fields, or None when the resource has none."""
    if not enum_fields:
        return None

    enum_names = list(enum_fields)
    enum_list = ", ".join(enum_names)
    return f"Filter by {enum_list} using RQL: eq({enum_names[0]},<value>)"


def build_path_params_required(path_parameters: dict[str, PathParameter]) -> str | None:
    """Say which path parameters the resource requires, or None when it has none."""
    if not path_parameters:
        return None

    param_list = ", ".join(f"{param_name}=<value>" for param_name in path_parameters)
    return f"This resource requires path parameters: {param_list}"


def find_related_resources(
    resource: str, endpoint_info: dict[str, Any], endpoints_registry: dict[str, Any]
) -> RelatedResources | None:
    """
    Find the parent, children and similar resources of a resource in the API paths.

    Args:
        resource: Resource name
        endpoint_info: Registry entry of the resource
        endpoints_registry: Registry of available endpoints

    Returns:
        The closest parent, up to MAX_CHILDREN children and up to MAX_SIMILAR similar resources,
        or None when the resource has none of them
    """
    resource_path = endpoint_info["path"]
    others = {
        other_resource: other_info
        for other_resource, other_info in endpoints_registry.items()
        if other_resource != resource
    }
    children = [
        RelatedResource(resource=child, summary=child_info["summary"])
        for child, child_info in others.items()
        if is_child(resource, resource_path, child, child_info["path"])
    ]
    similar = [
        RelatedResource(resource=similar_resource, summary=similar_info["summary"])
        for similar_resource, similar_info in others.items()
        if is_similar(resource, similar_resource)
    ]
    parent_paths = {
        candidate: candidate_info["path"]
        for candidate, candidate_info in others.items()
        if is_child(candidate, candidate_info["path"], resource, resource_path)
    }
    parent = None
    if parent_paths:
        closest_parent = max(parent_paths, key=lambda candidate: len(parent_paths[candidate]))
        parent_info = others[closest_parent]
        parent = RelatedResource(
            resource=closest_parent, summary=parent_info["summary"], path=parent_info["path"]
        )

    if parent is None and not children and not similar:
        return None

    return RelatedResources(
        parent=parent,
        children=children[:MAX_CHILDREN] or None,
        similar=similar[:MAX_SIMILAR] or None,
    )


def get_path_parameters(endpoint_info: dict[str, Any]) -> dict[str, PathParameter]:
    """Return the path parameters of a resource, with their type and description."""
    return {
        param_spec.get("name"): PathParameter(
            type=param_spec.get("schema", {}).get("type", "string"),
            description=param_spec.get("description", f"Path parameter: {param_spec.get('name')}"),
            required=param_spec.get("required", True),
        )
        for param_spec in endpoint_info.get("parameters", [])
        if param_spec.get("in") == "path"
    }


def get_query_enum_fields(endpoint_info: dict[str, Any]) -> dict[str, list[Any]]:
    """Return the query parameters with a fixed set of values, and those values."""
    return {
        param_spec.get("name"): param_spec.get("schema", {})["enum"]
        for param_spec in endpoint_info.get("parameters", [])
        if param_spec.get("in") == "query" and "enum" in param_spec.get("schema", {})
    }


def is_child(parent: str, parent_path: str, child: str, child_path: str) -> bool:
    """Tell whether a resource is under another one, in its name and in its API path."""
    return child_path.startswith(f"{parent_path}/") and child.startswith(f"{parent}.")


def is_similar(resource: str, other_resource: str) -> bool:
    """Tell whether two resources share their first two name segments and their depth."""
    resource_parts = resource.split(".")
    other_parts = other_resource.split(".")
    if len(resource_parts) != len(other_parts) or len(resource_parts) < SIMILAR_PREFIX_PARTS:
        return False

    return resource_parts[:SIMILAR_PREFIX_PARTS] == other_parts[:SIMILAR_PREFIX_PARTS]
