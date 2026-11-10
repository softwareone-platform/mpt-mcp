import pytest

from mpt_mcp.tools.query.select_fields import (
    add_always_selected,
    keep_allowed_fields,
    sanitize_select,
    selects_audit,
    top_level_field,
)

ORDER_FIELDS = frozenset(("audit", "id", "status"))


def test_add_always_selected_puts_them_first():
    result = add_always_selected(["+audit", "+status"], set(ORDER_FIELDS))

    assert result == ["id", "status", "+audit"]


def test_add_always_selected_only_id():
    result = add_always_selected(["audit"], set())

    assert result == ["id", "audit"]


def test_keep_allowed_fields_drops_unknown_fields():
    result = keep_allowed_fields(["audit.created.at", "orderNumber"], set(ORDER_FIELDS))

    assert result == ["audit.created.at"]


def test_keep_allowed_fields_no_schema():
    result = keep_allowed_fields(["audit", "orderNumber"], set())

    assert result == ["audit", "orderNumber"]


@pytest.mark.parametrize(
    ("select", "expected"),
    [
        (None, None),
        (" , ", " , "),
        ("audit,orderNumber", "id,status,audit"),
        ("-*,audit,orderNumber", "-*,+id,+status,+audit"),
        ("-*", "-*,+id,+status"),
    ],
)
def test_sanitize_select(select, expected):
    result = sanitize_select(select, set(ORDER_FIELDS))

    assert result == expected


@pytest.mark.parametrize(
    ("select", "expected"),
    [
        ("+id,+audit", True),
        ("audit.created.at", True),
        ("+id,+auditor", False),
        (None, False),
    ],
)
def test_selects_audit(select, expected):
    result = selects_audit(select)

    assert result is expected


def test_top_level_field():
    result = top_level_field("-product.name")

    assert result == "product"
