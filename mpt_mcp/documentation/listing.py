# Above this many pages, marketplace_docs_list suggests filtering by section
MANY_DOCS_RESULTS = 50


def describe_docs_filters(section: str | None, subsection: str | None, search: str | None) -> str:
    """
    Describe the filters marketplace_docs_list was called with.

    Args:
        section: Section filter
        subsection: Subsection filter
        search: Text search filter

    Returns:
        The filters given, e.g. section=api, search='orders', or none
    """
    filters = [
        f"section={section}" if section else "",
        f"subsection={subsection}" if subsection else "",
        f"search='{search}'" if search else "",
    ]
    return ", ".join(applied for applied in filters if applied) or "none"


def get_docs_list_tip(found: int, limit: int) -> str | None:
    """
    Suggest how to narrow down a long list of documentation pages.

    Args:
        found: Pages returned
        limit: Maximum pages that were asked for

    Returns:
        A tip when the list hit the limit or has many pages, or None
    """
    if found >= limit:
        return (
            f"Showing first {limit} results. Use 'section' or 'search' parameters to narrow down."
        )

    if found > MANY_DOCS_RESULTS:
        return "Consider using 'section' or 'subsection' filters to narrow down results."

    return None
