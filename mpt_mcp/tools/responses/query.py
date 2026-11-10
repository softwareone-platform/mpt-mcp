from typing import Any

from pydantic import Field

from mpt_mcp.tools.responses.base import ToolResponse, optional_field


class Pagination(ToolResponse):
    """Position of a page in the full result."""

    offset: int | None = optional_field("Items skipped before this page")
    limit: int | None = optional_field("Maximum items in this page")
    total: int | None = optional_field("Items that match the query across all pages")
    returned: int | None = optional_field("Items in this page")
    has_more: bool | None = optional_field("More items match the query after this page")
    next_offset: int | None = optional_field(
        "Offset of the next page, when has_more is true and the page has items"
    )


class QueryTruncation(ToolResponse):
    """Items left out of a page that did not fit in the result size limit."""

    requested: int = Field(description="Items the API returned for the page")
    suggested_limit: int = Field(
        description="Items that fit with this select: a limit that pages in parallel without cuts"
    )
    hint: str = Field(description="How to get the rest of the items")


class QueryMeta(ToolResponse):
    """Metadata of a Marketplace API response."""

    pagination: Pagination | None = optional_field("Pagination of a list response")
    omitted: list[str] | None = optional_field(
        "Fields left out by default; request them with select=+field"
    )
    truncated: QueryTruncation | None = optional_field(
        "Set when the page was cut to fit the result size limit"
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
