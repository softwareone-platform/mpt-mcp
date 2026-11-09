import difflib
import re
from dataclasses import dataclass
from typing import Any

from mpt_mcp.marketplace.endpoint_registry import EndpointRegistry
from mpt_mcp.marketplace.schemas import OpenAPISpec
from mpt_mcp.tools.results import tool_error

# Suggestions for an unknown resource: how many, and how close a misspelled name must be (0-1)
SUGGESTION_COUNT = 5
SUGGESTION_SIMILARITY = 0.6


@dataclass(frozen=True)
class MarketplaceSpec:
    """OpenAPI spec of the caller's endpoint, with the registry and audit fields built from it."""

    api_base_url: str
    audit_regex: re.Pattern[str]
    endpoints_registry: EndpointRegistry
    openapi: OpenAPISpec

    def get_categories(self) -> list[str]:
        """Return the resource categories, the first segment of the resource names, sorted."""
        return sorted({resource.partition(".")[0] for resource in self.endpoints_registry})

    def get_endpoint(self, resource: str) -> dict[str, Any]:
        """
        Return the registry entry of a resource.

        Args:
            resource: Resource name, e.g. commerce.orders

        Returns:
            Endpoint info of the resource: its API path, summary, description and parameters

        Raises:
            ToolError: The resource is unknown; the error suggests similar resources
        """
        endpoint = self.endpoints_registry.get(resource)
        if endpoint is not None:
            return endpoint

        hints: dict[str, Any] = {
            "hint": "Use marketplace_resources() to see all available resources",
            "available_categories": self.get_categories(),
        }
        similar_resources = self._suggest_resources(resource)
        if similar_resources:
            hints["did_you_mean"] = similar_resources

        raise tool_error(f"Unknown resource: '{resource}'", **hints)

    def get_item_fields(self, resource: str) -> set[str]:
        """Return the top-level fields of one item of a resource's GET response."""
        return set((self.get_item_schema(resource).get("properties") or {}).keys())

    def get_item_schema(self, resource: str) -> dict[str, Any]:
        """
        Return the schema of one item of a resource's GET response.

        Args:
            resource: Resource name

        Returns:
            Item schema with its $ref and allOf resolved, or {} when the spec does not describe it
        """
        path = (self.endpoints_registry.get(resource) or {}).get("path")
        return self.openapi.get_response_item_schema(path) if path else {}

    def _suggest_resources(self, resource: str) -> list[str]:
        # Resources that contain the name, or are contained in it, come first, closest spelling
        # first; then resources with a similar spelling, so typos such as catalog.prodcts match
        resource_lower = resource.lower()
        resources_by_lower = {known.lower(): known for known in self.endpoints_registry}
        containing = sorted(
            (
                known_lower
                for known_lower in resources_by_lower
                if resource_lower in known_lower or known_lower in resource_lower
            ),
            key=lambda known_lower: (
                -difflib.SequenceMatcher(None, resource_lower, known_lower).ratio()
            ),
        )
        similar = [
            resources_by_lower[known_lower]
            for known_lower in difflib.get_close_matches(
                resource_lower, resources_by_lower, n=SUGGESTION_COUNT, cutoff=SUGGESTION_SIMILARITY
            )
        ]
        containing_resources = [resources_by_lower[known_lower] for known_lower in containing]
        return list(dict.fromkeys(containing_resources + similar))[:SUGGESTION_COUNT]
