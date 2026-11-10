from pydantic import Field

from mpt_mcp.tools.responses.base import ToolResponse, optional_field


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

    text: str = Field(description="Page content in markdown, or one part of a long page")
    count: int = Field(description="Number of pages returned, always 1")
    total_characters: int | None = optional_field("Length of the page, when it comes in parts")
    next_offset: int | None = optional_field("Offset of the next part, when there is more to read")
    hint: str | None = optional_field("How to read the rest of the page")
