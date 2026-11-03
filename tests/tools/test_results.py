import json

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.results import (
    CHARACTER_LIMIT,
    add_page_position,
    fit_result_to_budget,
    tool_error,
)

PAGE_OFFSET = 20


@pytest.fixture
def big_page_factory():
    def factory(item_count):
        return {
            "$meta": {"pagination": {"offset": PAGE_OFFSET, "limit": item_count, "total": 500}},
            "data": [{"id": f"ORD-{index}", "notes": "x" * 1000} for index in range(item_count)],
        }

    return factory


def test_tool_error_without_details():
    result = tool_error("Unknown resource: x")

    assert str(result) == "Unknown resource: x"


def test_tool_error_appends_details_as_json():
    result = tool_error("Unknown resource: x", did_you_mean=["catalog.products"])

    assert str(result) == 'Unknown resource: x\n{"did_you_mean": ["catalog.products"]}'


@pytest.mark.parametrize(
    ("pagination", "item_count", "expected"),
    [
        (
            {"offset": 0, "limit": 10, "total": 25},
            10,
            {"returned": 10, "has_more": True, "next_offset": 10},
        ),
        (
            {"offset": 20, "limit": 10, "total": 25},
            5,
            {"returned": 5, "has_more": False, "next_offset": None},
        ),
        (
            {"offset": 0, "limit": 100, "total": 500},
            40,
            {"returned": 40, "has_more": True, "next_offset": 40},
        ),
        ({"offset": 0, "limit": 10}, 3, {"returned": 3}),
    ],
)
def test_add_page_position(pagination, item_count, expected):
    page = {
        "$meta": {"pagination": pagination},
        "data": [{"id": f"ORD-{index}"} for index in range(item_count)],
    }

    result = add_page_position(page)

    assert result["$meta"]["pagination"] == {**pagination, **expected}


@pytest.mark.parametrize(
    "response",
    [
        {"data": [{"id": "ORD-1"}]},
        {"id": "ORD-1"},
    ],
)
def test_add_page_position_needs_pagination(response):
    result = add_page_position(response)

    assert result == response


def test_fit_result_keeps_short_page(big_page_factory):
    page = big_page_factory(3)

    result = fit_result_to_budget(page)

    assert result == page


def test_fit_result_cuts_long_page(big_page_factory):
    page = big_page_factory(100)

    result = fit_result_to_budget(page)

    returned = len(result["data"])
    assert 0 < returned < 100
    assert len(json.dumps(result)) <= CHARACTER_LIMIT
    assert result["data"] == page["data"][:returned]
    assert result["$meta"]["pagination"] == page["$meta"]["pagination"]
    assert result["$meta"]["truncated"]["suggested_limit"] == returned
    assert result["$meta"]["truncated"]["requested"] == 100


def test_fit_result_ignores_single_item():
    order = {"id": "ORD-1", "notes": "x" * (CHARACTER_LIMIT * 2)}

    result = fit_result_to_budget(order)

    assert result == order


def test_fit_result_too_long_item_fails():
    page = {"data": [{"id": "ORD-1", "notes": "x" * (CHARACTER_LIMIT * 2)}]}

    with pytest.raises(ToolError, match="One item takes more than"):
        fit_result_to_budget(page)
