import datetime as dt

from mpt_mcp.prompts.commerce import (
    DUE_DAYS_DEFAULT,
    orders_by_status,
    recent_orders,
    subscriptions_due,
)


def test_recent_orders_sorts_by_creation():
    result = recent_orders()

    assert "resource=commerce.orders, order=-audit.created.at, select=" in result


def test_orders_by_status_sorts_by_update():
    result = orders_by_status("Failed")

    assert "rql=eq(status,Failed), order=-audit.updated.at" in result


def test_subscriptions_due_filters_window():
    today = dt.datetime.now(dt.UTC).date()
    until = today + dt.timedelta(days=DUE_DAYS_DEFAULT)

    result = subscriptions_due(days=DUE_DAYS_DEFAULT)

    assert (
        f"rql=and(eq(status,Active),ge(commitmentDate,{today}T00:00:00.000Z),"
        f"lt(commitmentDate,{until}T00:00:00.000Z))"
    ) in result
