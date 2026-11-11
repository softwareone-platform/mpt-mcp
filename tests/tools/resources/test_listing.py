import json

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.resources.listing import list_resources
from mpt_mcp.tools.results import CHARACTER_LIMIT

LONG_REGISTRY_SIZE = 300
LONG_CATEGORY_SIZE = 80


@pytest.fixture
def resources_registry():
    return {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "List products",
            "description": "Products of the catalog",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Draft", "Published"]}}
            ],
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "List orders",
            "parameters": [],
        },
        "commerce.orders.by_id": {
            "path": "/public/v1/commerce/orders/{id}",
            "summary": "Get an order",
            "parameters": [{"name": "id", "in": "path"}],
        },
    }


@pytest.fixture
def long_registry():
    summary = "x" * 100
    endpoint_info = {"path": "/public/v1/commerce/resource", "summary": summary}
    endpoint_info.update(description=summary, parameters=[])
    resource_names = [f"commerce.resource{index}" for index in range(LONG_REGISTRY_SIZE)]
    return dict.fromkeys(resource_names, endpoint_info)


@pytest.fixture
def listing_factory(spec_factory):
    def factory(endpoints_registry, category=None, search=None):
        return list_resources(
            spec_factory(registry=endpoints_registry),
            user_id=None,
            category=category,
            search=search,
        ).model_dump()

    return factory


def test_resources_lists_names_and_summaries(listing_factory, resources_registry):
    result = listing_factory(resources_registry)

    assert result["categories"] == {
        "catalog": [{"resource": "catalog.products", "summary": "List products"}],
        "commerce": [
            {"resource": "commerce.orders", "summary": "List orders"},
            {"resource": "commerce.orders.by_id", "summary": "Get an order"},
        ],
    }


def test_resources_category_adds_details(listing_factory, resources_registry):
    result = listing_factory(resources_registry, category="catalog")

    assert result["categories"] == {
        "catalog": [
            {
                "resource": "catalog.products",
                "summary": "List products",
                "path": "/public/v1/catalog/products",
                "description": "Products of the catalog",
                "filterable_fields": ["status"],
                "enum_fields": {"status": ["Draft", "Published"]},
            }
        ]
    }


def test_resources_search_matches_name_or_summary(listing_factory, resources_registry):
    result = listing_factory(resources_registry, search="ORDER")

    assert result["total_resources"] == 2
    assert list(result["categories"]) == ["commerce"]


def test_resources_long_list_keeps_names(listing_factory, long_registry):
    result = listing_factory(long_registry)

    entries = result["categories"]["commerce"]
    assert len(json.dumps(result)) <= CHARACTER_LIMIT
    assert len(entries) == LONG_REGISTRY_SIZE
    assert entries[0] == {"resource": "commerce.resource0"}
    assert "category or search" in result["note"]


def test_resources_long_category_keeps_summaries(listing_factory, long_registry):
    result = listing_factory(
        dict(list(long_registry.items())[:LONG_CATEGORY_SIZE]), category="commerce"
    )

    entries = result["categories"]["commerce"]
    assert entries[0] == {"resource": "commerce.resource0", "summary": "x" * 100}
    assert "marketplace_resource_info" in result["note"]


def test_resources_short_list_has_no_note(listing_factory, resources_registry):
    result = listing_factory(resources_registry)

    assert "note" not in result


def test_resources_unknown_category_fails(listing_factory, resources_registry):
    with pytest.raises(ToolError, match="Unknown category: commrce") as error:
        listing_factory(resources_registry, category="commrce")

    _, error_details = str(error.value).split("\n", 1)
    assert json.loads(error_details) == {"available_categories": ["catalog", "commerce"]}


def test_resources_tips_mention_omitted_fields(listing_factory, resources_registry):
    result = listing_factory(resources_registry)

    field_selection_tip = result["tips"]["field_selection"]
    assert "$meta.omitted" in field_selection_tip
    assert "+field" in field_selection_tip
