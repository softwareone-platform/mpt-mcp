from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError

from mpt_mcp.documentation import lifespan
from mpt_mcp.tools.annotations import READ_ONLY_REMOTE
from mpt_mcp.tools.responses import DocsIndexResponse, DocsListResponse, DocsReadResponse
from mpt_mcp.tools.results import cut_text_to_budget, tool_error

SERVER_NAME = "documentation"
DOCUMENTATION_CACHE_UNAVAILABLE_MSG = (
    "Documentation cache is not available. Please configure GITBOOK_API_KEY and GITBOOK_SPACE_ID."
)
MANY_DOCS_RESULTS = 50


async def marketplace_docs_index() -> DocsIndexResponse:
    """
    Get the documentation table of contents.

    Returns:
        Total page count and the documentation sections with their subsections and page counts
    """
    await lifespan.initialize_documentation_cache()
    dc = lifespan.documentation_state.cache
    if not dc or not dc.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    return DocsIndexResponse.model_validate(await dc.get_documentation_index())


async def marketplace_docs_list(
    section: str | None = None,
    subsection: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> DocsListResponse:
    """
    List documentation pages, optionally filtered.

    Args:
        section: Only pages of this section (see marketplace_docs_index)
        subsection: Only pages of this subsection
        search: Only pages whose title or path contains this text
        limit: Max pages to return (default 100)

    Returns:
        Matching pages with their docs:// uri, title and public browser_url when available
    """
    await lifespan.initialize_documentation_cache()
    dc = lifespan.documentation_state.cache
    if not dc or not dc.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    resources = await dc.list_resources(
        section=section, subsection=subsection, search=search, limit=limit
    )
    resources_for_response = []
    for resource in resources:
        entry = dict(resource)
        if resource.get("metadata", {}).get("browser_url"):
            entry["browser_url"] = resource["metadata"]["browser_url"]
        resources_for_response.append(entry)
    filters = []
    if section:
        filters.append(f"section={section}")
    if subsection:
        filters.append(f"subsection={subsection}")
    if search:
        filters.append(f"search='{search}'")
    result = {
        "total": len(resources_for_response),
        "resources": resources_for_response,
        "filters_applied": ", ".join(filters) if filters else "none",
        "usage": (
            "Use marketplace_docs_read(uri='docs://path') to read a page. "
            "Prefer showing users the browser_url (public link) when present; "
            "do not show internal uri or id to end users."
        ),
    }
    if len(resources) >= limit:
        result["tip"] = (
            f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
        )
    elif len(resources) > MANY_DOCS_RESULTS:
        result["tip"] = "Consider using 'section' or 'subsection' filters to narrow down results."

    return DocsListResponse.model_validate(result)


async def marketplace_docs_read(uri: str, offset: int = 0) -> DocsReadResponse:
    """
    Read a documentation page.

    Long pages come in parts: next_offset is set when there is more to read.

    Args:
        uri: Page uri from marketplace_docs_list (e.g. docs://help-and-support/contact-support)
        offset: Character to start reading from, the next_offset of the previous part

    Returns:
        Page content in markdown, or one part of it
    """
    await lifespan.initialize_documentation_cache()
    dc = lifespan.documentation_state.cache
    if not dc or not dc.is_enabled:
        raise tool_error(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    page_content = await dc.get_resource(uri)
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


async def get_documentation_page(path: str) -> str:
    """
    Return the markdown of the documentation page at docs://{path}.

    Args:
        path: Page path, the uri without docs://

    Returns:
        Page content in markdown

    Raises:
        ResourceError: The documentation is not configured or the page does not exist
    """
    uri = f"docs://{path}"
    await lifespan.initialize_documentation_cache()
    dc = lifespan.documentation_state.cache
    if not dc or not dc.is_enabled:
        raise ResourceError(DOCUMENTATION_CACHE_UNAVAILABLE_MSG)

    page_content = await dc.get_resource(uri)
    if page_content is None:
        raise ResourceError(
            f"Documentation page not found: {uri}. Use marketplace_docs_list() to see "
            "available pages"
        )

    return page_content


def create_documentation_server() -> FastMCP:
    """
    Create the server of the Marketplace documentation tools and the docs:// resource.

    The MCP server mounts it without a namespace, so the tool names do not change. It has no
    lifespan: the HTTP server loads the documentation at startup with documentation_lifespan,
    and stdio loads it on the first documentation call.

    Returns:
        Documentation server to mount
    """
    docs_server = FastMCP(SERVER_NAME)
    for tool, title in (
        (marketplace_docs_index, "Documentation index"),
        (marketplace_docs_list, "List documentation pages"),
        (marketplace_docs_read, "Read a documentation page"),
    ):
        docs_server.tool(title=title, annotations=READ_ONLY_REMOTE)(tool)
    docs_server.resource(
        "docs://{path*}",
        name="Documentation",
        description="Documentation pages. Use marketplace_docs_list() for available URIs.",
        mime_type="text/markdown",
    )(get_documentation_page)
    return docs_server
