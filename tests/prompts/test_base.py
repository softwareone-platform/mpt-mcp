from mpt_mcp.prompts.base import query_request


def test_query_request_lists_arguments():
    result = query_request(
        resource="commerce.orders",
        rql="eq(status,Failed)",
        order="-audit.created.at",
        select="-*,+id",
        summary="as a list",
    )

    assert result.startswith(
        "Call marketplace_query with resource=commerce.orders, rql=eq(status,Failed), "
        "order=-audit.created.at, select=-*,+id. Show the items as a list,"
    )


def test_query_request_skips_empty_arguments():
    result = query_request(resource="accounts.buyers", select="-*,+id", summary="as a list")

    assert "Call marketplace_query with resource=accounts.buyers, select=-*,+id." in result
