from typing import Any

from pydantic import Field

from mpt_mcp.tools.responses.base import ToolResponse, optional_field


class RelatedResource(ToolResponse):
    """Resource related to the described one."""

    resource: str = Field(description="Resource name")
    summary: str = Field(description="What the resource returns")
    path: str | None = optional_field("API path, for the parent resource")


class RelatedResources(ToolResponse):
    """Resources next to the described one in the API paths."""

    parent: RelatedResource | None = optional_field("Resource one path segment up")
    children: list[RelatedResource] | None = optional_field("Up to 10 resources under this one")
    similar: list[RelatedResource] | None = optional_field(
        "Up to 5 resources in the same category, at the same depth"
    )


class PathParameter(ToolResponse):
    """Path parameter of a resource."""

    type: str = Field(description="JSON type of the value")
    description: str = Field(description="What the parameter identifies")
    required: bool = Field(description="Whether the parameter must be given")


class ResourceInfoResponse(ToolResponse):
    """Description of a resource: parameters, enum values, related resources and examples."""

    resource: str = Field(description="Resource name")
    path: str = Field(description="API path, with its path parameters in braces")
    summary: str = Field(description="What the resource returns")
    description: str = Field(description="Longer description from the OpenAPI spec")
    operation_parameters: list[dict[str, Any]] = Field(
        alias="parameters", description="OpenAPI parameters of the GET operation"
    )
    response_schema: dict[str, Any] = Field(description="Response schema from the OpenAPI spec")
    common_parameters: dict[str, str] = Field(description="marketplace_query arguments")
    omitted_fields_note: str = Field(description="How to request fields omitted by default")
    example_queries: list[str] = Field(description="marketplace_query calls for the resource")
    enum_fields: dict[str, list[Any]] | None = optional_field(
        "Query parameters with a fixed set of values, and those values"
    )
    filtering_tips: str | None = optional_field("How to filter by the enum fields")
    path_parameters: dict[str, PathParameter] | None = optional_field(
        "Path parameters to pass in path_params"
    )
    path_params_required: str | None = optional_field("Path parameters the resource requires")
    related_resources: RelatedResources | None = optional_field(
        "Parent, child and similar resources"
    )
