from typing import Any

from pydantic import Field

from mpt_mcp.tools.responses.base import ToolResponse, optional_field


class SchemaField(ToolResponse):
    """Top-level field of a resource item."""

    type: str = Field(description="JSON type, or unknown when the spec does not say")
    description: str = Field(description="Field description from the OpenAPI spec")
    enum: list[Any] | None = optional_field("Values the field can take")
    valid_values: list[Any] | None = optional_field("Values the field can take")
    example: Any = optional_field("Example value")
    format: str | None = optional_field("JSON schema format, such as date-time")
    nested_fields: dict[str, dict[str, Any]] | None = optional_field(
        "First 5 fields of an object field, with their type and description"
    )


class FilteringHints(ToolResponse):
    """RQL filters built from the resource fields."""

    simple_filters: list[str] = Field(description="Equality filters on scalar fields")
    search_fields: list[str] = Field(description="Text search filters on string fields")
    enum_filters: list[str] = Field(description="Filters on fields with a fixed set of values")


class ResourceSchemaResponse(ToolResponse):
    """Response schema of a resource and the fields of its items."""

    resource: str = Field(description="Resource name")
    path: str = Field(description="API path, with its path parameters in braces")
    summary: str = Field(description="What the resource returns")
    description: str = Field(description="Longer description from the OpenAPI spec")
    response_schema: dict[str, Any] | None = optional_field(
        "Response schema from the OpenAPI spec; list resources wrap their items in data"
    )
    fields: dict[str, SchemaField] | None = optional_field(
        "Top-level fields of one item, usable in select and RQL filters"
    )
    filtering_hints: FilteringHints | None = optional_field("RQL filters built from the fields")
    common_queries: dict[str, str] = Field(
        description="marketplace_query calls for the resource, built from the fields of its items"
    )
