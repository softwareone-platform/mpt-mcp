import pytest

from mpt_mcp.documentation import listing


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ((None, None, None), "none"),
        (("api", None, "orders"), "section=api, search='orders'"),
        (("api", "commerce", None), "section=api, subsection=commerce"),
    ],
)
def test_describe_docs_filters(filters, expected):
    result = listing.describe_docs_filters(*filters)

    assert result == expected


@pytest.mark.parametrize(
    ("found", "expected_start"),
    [
        (100, "Showing first 100 results"),
        (listing.MANY_DOCS_RESULTS + 1, "Consider using 'section'"),
    ],
)
def test_get_docs_list_tip(found, expected_start):
    result = listing.get_docs_list_tip(found, 100)

    assert result.startswith(expected_start)


def test_get_docs_list_tip_for_few_pages():
    result = listing.get_docs_list_tip(listing.MANY_DOCS_RESULTS, 100)

    assert result is None
