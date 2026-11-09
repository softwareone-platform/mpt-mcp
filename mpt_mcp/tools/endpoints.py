import difflib
from typing import TYPE_CHECKING, Any

from mpt_mcp.tools.results import tool_error

if TYPE_CHECKING:
    from collections.abc import Iterable

# Suggestions for an unknown resource: how many, and how close a misspelled name must be (0-1)
SUGGESTION_COUNT = 5
SUGGESTION_SIMILARITY = 0.6


def get_endpoint(resource: str, endpoints_registry: dict[str, Any]) -> dict[str, Any]:
    """
    Return the registry entry of a resource.

    Args:
        resource: Resource name, e.g. commerce.orders
        endpoints_registry: Registry of available endpoints

    Returns:
        Endpoint info of the resource: its API path, summary, description and parameters

    Raises:
        ToolError: The resource is unknown; the error suggests similar resources
    """
    endpoint: dict[str, Any] | None = endpoints_registry.get(resource)
    if endpoint is not None:
        return endpoint

    hints: dict[str, Any] = {
        "hint": "Use marketplace_resources() to see all available resources",
        "available_categories": sorted({known.split(".")[0] for known in endpoints_registry}),
    }
    similar_resources = suggest_resources(resource, endpoints_registry)
    if similar_resources:
        hints["did_you_mean"] = similar_resources

    raise tool_error(f"Unknown resource: '{resource}'", **hints)


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
