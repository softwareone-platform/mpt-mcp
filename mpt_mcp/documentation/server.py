from fastmcp.dependencies import Depends
from fastmcp.exceptions import ResourceError
from fastmcp.server.providers import LocalProvider

from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.store import get_documentation_cache
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.responses import (
    DocsIndexResponse,
    DocsListResponse,
    DocsPage,
    DocsReadResponse,
)
from mpt_mcp.tools.results import cut_text_to_budget, tool_error

DOCUMENTATION_CACHE_UNAVAILABLE_MSG = (
    "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
)
MANY_DOCS_RESULTS = 50
documentation_provider = LocalProvider()


@documentation_provider.tool(title="Documentation index", annotations=READ_ONLY_REMOTE)
async def marketplace_docs_index(
    docs_cache: DocumentationCache = Depends(get_documentation_cache),  # noqa: WPS404
) -> DocsIndexResponse:
    """
    Get the documentation table of contents.

    Args:
        docs_cache: Documentation cache, injected by FastMCP (not a tool argument)

    Returns:
        Total page count and the documentation sections with their subsections and page counts
    """
    if not docs_cache.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    return DocsIndexResponse.model_validate(await docs_cache.get_documentation_index())


@documentation_provider.tool(title="List documentation pages", annotations=READ_ONLY_REMOTE)
async def marketplace_docs_list(
    section: str | None = None,
    subsection: str | None = None,
    search: str | None = None,
    limit: int = 100,
    docs_cache: DocumentationCache = Depends(get_documentation_cache),  # noqa: WPS404
) -> DocsListResponse:
    """
    List documentation pages, optionally filtered.

    Args:
        section: Only pages of this section (see marketplace_docs_index)
        subsection: Only pages of this subsection
        search: Only pages whose title or path contains this text
        limit: Max pages to return (default 100)
        docs_cache: Documentation cache, injected by FastMCP (not a tool argument)

    Returns:
        Matching pages with their docs:// uri, title and public browser_url when available
    """
    if not docs_cache.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    resources = await docs_cache.list_resources(
        section=section, subsection=subsection, search=search, limit=limit
    )
    pages = [
        DocsPage.model_validate({
            **resource,
            "browser_url": resource.get("metadata", {}).get("browser_url") or None,
        })
        for resource in resources
    ]
    filters = []
    if section:
        filters.append(f"section={section}")
    if subsection:
        filters.append(f"subsection={subsection}")
    if search:
        filters.append(f"search='{search}'")
    tip = None
    if len(resources) >= limit:
        tip = f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
    elif len(resources) > MANY_DOCS_RESULTS:
        tip = "Consider using 'section' or 'subsection' filters to narrow down results."

    return DocsListResponse(
        total=len(pages),
        resources=pages,
        filters_applied=", ".join(filters) if filters else "none",
        usage=(
            "Use marketplace_docs_read(uri='docs://path') to read a page. "
            "Prefer showing users the browser_url (public link) when present; "
            "do not show internal uri or id to end users."
        ),
        tip=tip,
    )


@documentation_provider.tool(title="Read a documentation page", annotations=READ_ONLY_REMOTE)
async def marketplace_docs_read(
    uri: str,
    offset: int = 0,
    docs_cache: DocumentationCache = Depends(get_documentation_cache),  # noqa: WPS404
) -> DocsReadResponse:
    """
    Read a documentation page.

    Long pages come in parts: next_offset is set when there is more to read.

    Args:
        uri: Page uri from marketplace_docs_list (e.g. docs://help-and-support/contact-support)
        offset: Character to start reading from, the next_offset of the previous part
        docs_cache: Documentation cache, injected by FastMCP (not a tool argument)

    Returns:
        Page content in markdown, or one part of it
    """
    if not docs_cache.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    page_content = await docs_cache.get_resource(uri)
    if page_content is None:
        raise tool_error(
            f"Documentation page not found: {uri}",
            hint="Use marketplace_docs_list() to see available pages.",
        )

    page_part, next_offset = cut_text_to_budget(page_content, offset)
    if next_offset is None:
        return DocsReadResponse(text=page_part, count=1)

    return DocsReadResponse(
        text=page_part,
        count=1,
        total_characters=len(page_content),
        next_offset=next_offset,
        hint=(
            f"The page is longer than one result. Read the rest with offset={next_offset}, "
            "or give the user the page's browser_url from marketplace_docs_list."
        ),
    )


@documentation_provider.resource(
    "docs://{path*}",
    name="Documentation",
    description="Documentation pages. Use marketplace_docs_list() for available URIs.",
    mime_type="text/markdown",
)
async def get_documentation_page(
    path: str,
    docs_cache: DocumentationCache = Depends(get_documentation_cache),  # noqa: WPS404
) -> str:
    """
    Return the markdown of the documentation page at docs://{path}.

    Args:
        path: Page path, the uri without docs://
        docs_cache: Documentation cache, injected by FastMCP

    Returns:
        Page content in markdown

    Raises:
        ResourceError: The documentation is not configured or the page does not exist
    """
    uri = f"docs://{path}"
    if not docs_cache.is_enabled:
        raise ResourceError(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    page_content = await docs_cache.get_resource(uri)
    if page_content is None:
        raise ResourceError(
            f"Documentation page not found: {uri}. Use marketplace_docs_list() to see "
            "available pages"
        )

    return page_content
