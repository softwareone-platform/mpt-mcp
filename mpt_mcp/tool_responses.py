from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def optional_field(description: str, alias: str | None = None) -> Any:
    """
    Declare an optional response field that is left out of the response when it has no value.

    Args:
        description: Field description sent to MCP clients in the tool's output schema
        alias: Name of the field in the response, when it is not a valid Python name

    Returns:
        Pydantic field that defaults to None and is not serialized while it is None
    """
    return Field(
        None,
        alias=alias,
        description=description,
        exclude_if=lambda field_value: field_value is None,
    )


class ToolResponse(BaseModel):
    """Base of the tool responses: keys the model does not declare are kept as they are."""

    model_config = ConfigDict(
        extra="allow", serialize_by_alias=True, validate_by_alias=True, validate_by_name=True
    )


class Pagination(ToolResponse):
    """Position of a page in the full result."""

    offset: int | None = optional_field("Items skipped before this page")
    limit: int | None = optional_field("Maximum items in this page")
    total: int | None = optional_field("Items that match the query across all pages")


class QueryMeta(ToolResponse):
    """Metadata of a Marketplace API response."""

    pagination: Pagination | None = optional_field("Pagination of a list response")
    omitted: list[str] | None = optional_field(
        "Fields left out by default; request them with select=+field"
    )


class QueryResponse(ToolResponse):
    """
    Marketplace API response.

    List resources return a page of items in data; resources that return a single item return
    its fields at the top level.
    """

    meta: QueryMeta | None = optional_field("Pagination and omitted fields", alias="$meta")
    data: list[dict[str, Any]] | None = optional_field("Items of the page, for list resources")
    result: Any = optional_field(
        "Response of resources that return a plain value instead of an object"
    )


class QueryTemplate(ToolResponse):
    """Ready-to-use marketplace_query call."""

    name: str = Field(description="Template name")
    description: str = Field(description="What the query returns")
    query: str = Field(description="marketplace_query call to run, with xxxx placeholders")
    use_case: str = Field(description="When to use the template")
    available_statuses: list[str] | None = optional_field(
        "Status values to use in the template's filter"
    )


class QueryTemplateCategory(ToolResponse):
    """Query templates of one resource area."""

    description: str = Field(description="Area the templates cover")
    templates: list[QueryTemplate] = Field(description="Templates of the area")


class QueryTips(ToolResponse):
    """How to adapt the templates."""

    how_to_use: list[str] = Field(description="Steps to adapt a template")
    rql_basics: dict[str, str] = Field(description="RQL operators with their meaning")


class QuickQueriesResponse(ToolResponse):
    """Query templates by resource area."""

    orders: QueryTemplateCategory = Field(description="Order queries")
    products: QueryTemplateCategory = Field(description="Product queries")
    agreements: QueryTemplateCategory = Field(description="Agreement queries")
    subscriptions: QueryTemplateCategory = Field(description="Subscription queries")
    accounts: QueryTemplateCategory = Field(description="Account queries")
    tips: QueryTips = Field(description="How to adapt the templates")


class ResourceEntry(ToolResponse):
    """Queryable resource; its path, description and query parameters come with a category."""

    resource: str = Field(description="Resource name to pass to marketplace_query")
    summary: str = Field(description="What the resource returns")
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
    common_queries: dict[str, str] = Field(description="Query string patterns for the resource")


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


class DocsSubsection(ToolResponse):
    """Subsection of the documentation."""

    name: str = Field(description="Subsection name, the second segment of its page uris")
    pages: int = Field(description="Number of pages")


class DocsSection(ToolResponse):
    """Section of the documentation."""

    name: str = Field(description="Section name, to filter marketplace_docs_list by")
    total_pages: int = Field(description="Number of pages, subsections included")
    subsections: list[DocsSubsection] = Field(description="Subsections of the section")


class DocsIndexResponse(ToolResponse):
    """Table of contents of the documentation."""

    total_pages: int = Field(description="Number of pages in the documentation")
    sections: list[DocsSection] = Field(description="Sections, in alphabetical order")


class DocsPageMetadata(ToolResponse):
    """GitBook metadata of a documentation page."""

    id: str = Field(description="GitBook page ID; do not show it to users")
    path: str = Field(description="Page path in the documentation")
    title: str = Field(description="Page title")
    browser_url: str | None = optional_field("Public link to the page")


class DocsPage(ToolResponse):
    """Documentation page."""

    uri: str = Field(description="docs:// uri to pass to marketplace_docs_read")
    name: str = Field(description="Page title")
    description: str = Field(description="Short description of the page")
    mime_type: str = Field(alias="mimeType", description="Format of the page content")
    metadata: DocsPageMetadata = Field(description="GitBook metadata of the page")
    browser_url: str | None = optional_field("Public link to the page; show it to users")


class DocsListResponse(ToolResponse):
    """Documentation pages that match the filters."""

    total: int = Field(description="Number of pages returned")
    resources: list[DocsPage] = Field(description="Matching pages")
    filters_applied: str = Field(description="Filters used, or none")
    usage: str = Field(description="How to read a page and which link to show users")
    tip: str | None = optional_field("How to narrow down many results")


class DocsReadResponse(ToolResponse):
    """Content of a documentation page."""

    text: str = Field(description="Page content in markdown")
    count: int = Field(description="Number of pages returned, always 1")


class SpecCacheInfo(ToolResponse):
    """State of the OpenAPI spec cache on disk."""

    cache_directory: str = Field(description="Directory of the cache files")
    total_entries: int = Field(description="Cached specs")
    valid_entries: int = Field(description="Cached specs younger than the TTL")
    expired_entries: int = Field(description="Cached specs older than the TTL")
    total_size_bytes: int = Field(description="Size of the cache files")
    ttl_hours: float = Field(description="Time a cached spec stays valid")


class CacheInfoResponse(ToolResponse):
    """State of the OpenAPI spec cache."""

    cache_status: str = Field(description="Whether the cache is enabled")
    cache_info: SpecCacheInfo = Field(description="State of the cache on disk")
    note: str = Field(description="What the cache is for")


class RefreshCacheResponse(ToolResponse):
    """Result of reloading the OpenAPI spec."""

    success: bool = Field(description="Whether the spec was reloaded, always true")
    message: str = Field(description="Result of the refresh")
    endpoints_count: int = Field(description="Resources found in the reloaded spec")


class DocumentationCacheState(ToolResponse):
    """State of the documentation cache."""

    enabled: bool = Field(description="Whether GitBook is configured")
    total_pages: int = Field(description="Pages in the cache")
    cache_info: dict[str, Any] | None = optional_field("Refresh state of the cache")


class TokenCacheState(ToolResponse):
    """State of the token validation cache."""

    enabled: bool = Field(description="Whether the cache is available")
    cache_stats: dict[str, Any] | None = optional_field("Cached validations and their TTL")
    description: str | None = optional_field("What the cache is for")
    error: str | None = optional_field("Why the cache is not available")


class ResourcesInfoResponse(ToolResponse):
    """State of the documentation and token validation caches."""

    documentation: DocumentationCacheState = Field(description="Documentation cache")
    token_validation: TokenCacheState = Field(description="Token validation cache")
