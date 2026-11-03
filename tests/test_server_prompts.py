import datetime as dt

from mpt_mcp.server_prompts import (
    DUE_DAYS_DEFAULT,
    orders_by_status,
    query_request,
    recent_orders,
    search_buyers,
    subscriptions_due,
)


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


def test_recent_orders_sorts_by_creation():
    result = recent_orders()

    assert "resource=commerce.orders, order=-audit.created.at, select=" in result


def test_orders_by_status_sorts_by_update():
    result = orders_by_status("Failed")

    assert "rql=eq(status,Failed), order=-audit.updated.at" in result


def test_search_buyers_searches_name():
    result = search_buyers("Contoso")

    assert "resource=accounts.buyers, rql=ilike(name,*Contoso*)" in result


def test_subscriptions_due_filters_window():
    today = dt.datetime.now(dt.UTC).date()
    until = today + dt.timedelta(days=DUE_DAYS_DEFAULT)

    result = subscriptions_due(days=DUE_DAYS_DEFAULT)

    assert (
        f"rql=and(eq(status,Active),ge(commitmentDate,{today}T00:00:00.000Z),"
        f"lt(commitmentDate,{until}T00:00:00.000Z))"
    ) in result
