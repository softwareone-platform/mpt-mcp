from typing import Any

from pydantic import Field

from mpt_mcp.tools.responses.base import ToolResponse, optional_field


class ResourceEntry(ToolResponse):
    """Queryable resource; its path, description and query parameters come with a category."""

    resource: str = Field(description="Resource name to pass to marketplace_query")
    summary: str | None = optional_field("What the resource returns, unless the list is too long")
    path: str | None = optional_field("API path, with its path parameters in braces")
    description: str | None = optional_field("Longer description from the OpenAPI spec")
    filterable_fields: list[str] | None = optional_field("First query parameters of the resource")
    enum_fields: dict[str, list[Any]] | None = optional_field(
        "Query parameters with a fixed set of values, and those values"
    )


class ResourcesResponse(ToolResponse):
    """Queryable resources of the caller's endpoint, by category."""

    api_endpoint: str = Field(description="Marketplace API endpoint the resources belong to")
    user: str = Field(description="Caller's user or token ID, or unknown")
    total_resources: int = Field(description="Number of resources returned")
    categories: dict[str, list[ResourceEntry]] = Field(
        description="Resources by category, the first segment of the resource name"
    )
    usage: dict[str, str] = Field(description="Which tool to use for each next step")
    tips: dict[str, str] = Field(description="How to filter, paginate, sort and select fields")
    note: str | None = optional_field("Set when the list was shortened to fit in one result")


class AuditFieldsResponse(ToolResponse):
    """
    Audit events of one resource, or of every resource.

    Each event is filtered and sorted by audit.<event>.at (when) and audit.<event>.by (who).
    """

    resource: str | None = optional_field("Resource the events belong to, when one was asked")
    events: list[str] | None = optional_field("Audit events of the resource")
    hint: str | None = optional_field("Why the resource has no events")
    by_resource: dict[str, list[str]] | None = optional_field(
        "Audit events by resource, when no resource was asked"
    )
