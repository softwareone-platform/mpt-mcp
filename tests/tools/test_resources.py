import json

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.resources import (
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
    marketplace_resource_info,
)
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


def test_resource_info_notes_omitted_fields(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="commerce.orders",
        endpoints_registry=endpoints_registry,
    )

    assert "omitted_fields_note" in result
    assert "omitted" in result["omitted_fields_note"].lower()
    assert "$meta.omitted" in result["omitted_fields_note"]
    assert "select=+field" in result["omitted_fields_note"]


def test_resource_info_select_documents_omitted(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="commerce.orders",
        endpoints_registry=endpoints_registry,
    )

    select_doc = result["common_parameters"]["select"]
    assert "select=-*,+id,+name" in select_doc
    assert "$meta.omitted" in select_doc


def test_resources_lists_names_and_summaries(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com", user_id=None, endpoints_registry=resources_registry
    )

    assert result["categories"] == {
        "catalog": [{"resource": "catalog.products", "summary": "List products"}],
        "commerce": [
            {"resource": "commerce.orders", "summary": "List orders"},
            {"resource": "commerce.orders.by_id", "summary": "Get an order"},
        ],
    }


def test_resources_category_adds_details(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com",
        user_id=None,
        endpoints_registry=resources_registry,
        category="catalog",
    )

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


def test_resources_search_matches_name_or_summary(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com",
        user_id=None,
        endpoints_registry=resources_registry,
        search="ORDER",
    )

    assert result["total_resources"] == 2
    assert list(result["categories"]) == ["commerce"]


def test_resources_long_list_keeps_names(long_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com", user_id=None, endpoints_registry=long_registry
    )

    entries = result["categories"]["commerce"]
    assert len(json.dumps(result)) <= CHARACTER_LIMIT
    assert len(entries) == LONG_REGISTRY_SIZE
    assert entries[0] == {"resource": "commerce.resource0"}
    assert "category or search" in result["note"]


def test_resources_long_category_keeps_summaries(long_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com",
        user_id=None,
        endpoints_registry=dict(list(long_registry.items())[:LONG_CATEGORY_SIZE]),
        category="commerce",
    )

    entries = result["categories"]["commerce"]
    assert entries[0] == {"resource": "commerce.resource0", "summary": "x" * 100}
    assert "marketplace_resource_info" in result["note"]


def test_resources_short_list_has_no_note(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com", user_id=None, endpoints_registry=resources_registry
    )

    assert "note" not in result


def test_resources_unknown_category_fails(resources_registry):
    with pytest.raises(ToolError, match="Unknown category: commrce") as error:
        execute_marketplace_resources(
            api_base_url="https://api.test.com",
            user_id=None,
            endpoints_registry=resources_registry,
            category="commrce",
        )

    _, error_details = str(error.value).split("\n", 1)
    assert json.loads(error_details) == {"available_categories": ["catalog", "commerce"]}


def test_resources_tips_mention_omitted_fields():
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "method": "GET",
            "summary": "List orders",
            "parameters": [],
        }
    }

    result = execute_marketplace_resources(
        endpoints_registry=mock_registry,
        api_base_url="https://api.test.com",
        user_id="test-user",
    )

    assert "tips" in result
    assert "field_selection" in result["tips"]
    field_selection_tip = result["tips"]["field_selection"]
    assert "omitted" in field_selection_tip.lower() or "$meta.omitted" in field_selection_tip
    assert "select=+field" in field_selection_tip or "+field" in field_selection_tip


def test_resource_info_handles_unknown_resource(endpoints_registry):
    with pytest.raises(ToolError, match=r"Unknown resource: unknown\.resource"):
        execute_marketplace_resource_info(
            resource="unknown.resource",
            endpoints_registry=endpoints_registry,
        )


def test_resource_schema_lists_item_fields(endpoints_registry, openapi_spec_factory):
    result = execute_marketplace_resource_schema(
        resource="commerce.orders",
        openapi_spec=openapi_spec_factory(["id", "status"]),
        endpoints_registry=endpoints_registry,
    )

    assert list(result["fields"]) == ["id", "status"]


def test_resource_schema_resolves_field_refs(endpoints_registry):
    order_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "audit": {"allOf": [{"$ref": "#/components/schemas/Audit"}]},
        },
    }
    list_schema = {"properties": {"data": {"type": "array", "items": {"$ref": "#/order"}}}}
    response = {"200": {"content": {"application/json": {"schema": list_schema}}}}
    openapi_spec = {
        "order": order_schema,
        "components": {"schemas": {"Audit": {"properties": {"created": {"type": "object"}}}}},
        "paths": {"/public/v1/commerce/orders": {"get": {"responses": response}}},
    }

    result = execute_marketplace_resource_schema(
        resource="commerce.orders", openapi_spec=openapi_spec, endpoints_registry=endpoints_registry
    )

    assert result["fields"]["audit"]["type"] == "object"
    assert result["filtering_hints"]["simple_filters"] == ["eq(id,value)"]


def test_resource_info_shows_children(spec_factory):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [],
        },
        "catalog.products.by_id.items": {
            "path": "/public/v1/catalog/products/{id}/items",
            "summary": "Product items",
            "parameters": [],
        },
    }

    result = (
        marketplace_resource_info("catalog.products", spec=spec_factory(registry=mock_registry))
    ).model_dump()

    assert "related_resources" in result
    assert "children" in result["related_resources"]
    child_resources = [resource["resource"] for resource in result["related_resources"]["children"]]
    assert "catalog.products.by_id" in child_resources


def test_resource_info_shows_parent(spec_factory):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [],
        },
    }

    result = (
        marketplace_resource_info(
            "catalog.products.by_id", spec=spec_factory(registry=mock_registry)
        )
    ).model_dump()

    assert "related_resources" in result
    assert "parent" in result["related_resources"]
    assert result["related_resources"]["parent"]["resource"] == "catalog.products"


def test_resource_info_shows_multiple_examples(
    spec_factory,
):
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [
                {
                    "name": "status",
                    "in": "query",
                    "schema": {"type": "string", "enum": ["Active", "Completed", "Cancelled"]},
                }
            ],
        }
    }

    result = (
        marketplace_resource_info("commerce.orders", spec=spec_factory(registry=mock_registry))
    ).model_dump()

    assert "example_queries" in result
    assert len(result["example_queries"]) > 1
    example_strings = " ".join(result["example_queries"])
    assert "Active" in example_strings or "Completed" in example_strings


def test_resource_info_shows_filtering_tips(
    spec_factory,
):
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Active", "Completed"]}}
            ],
        }
    }

    result = (
        marketplace_resource_info("commerce.orders", spec=spec_factory(registry=mock_registry))
    ).model_dump()

    assert "filtering_tips" in result
    assert "status" in result["filtering_tips"]
