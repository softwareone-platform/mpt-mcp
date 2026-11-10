from typing import Any

from mpt_mcp.tools.responses import RelatedResource, RelatedResources

MAX_CHILDREN = 10
MAX_SIMILAR = 5
# Resources are similar when they share their first two name segments, e.g. commerce.orders
SIMILAR_PREFIX_PARTS = 2


def find_related_resources(  # noqa: WPS210
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
