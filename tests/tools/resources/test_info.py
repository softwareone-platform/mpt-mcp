import pytest

from mpt_mcp.tools.resources.info import describe_resource_info


@pytest.fixture
def products_registry():
    return {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Draft", "Published"]}}
            ],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [{"name": "id", "in": "path", "schema": {"type": "string"}}],
        },
        "catalog.products.by_id.items": {
            "path": "/public/v1/catalog/products/{id}/items",
            "summary": "Product items",
            "parameters": [],
        },
        "catalog.listings": {
            "path": "/public/v1/catalog/listings",
            "summary": "Listings",
            "parameters": [],
        },
        "catalog.items": {
            "path": "/public/v1/catalog/items",
            "summary": "Items",
            "parameters": [],
        },
        "catalog.products.search": {
            "path": "/public/v1/catalog/products/search",
            "summary": "Search products",
            "parameters": [],
        },
    }


@pytest.fixture
def resource_info_factory(products_registry):
    def factory(resource):
        return describe_resource_info(
            resource, products_registry[resource], products_registry
        ).model_dump()

    return factory


def test_resource_info_notes_omitted_fields(resource_info_factory):
    result = resource_info_factory("catalog.products")

    assert "$meta.omitted" in result["omitted_fields_note"]
    assert "select=+field" in result["omitted_fields_note"]


def test_resource_info_select_documents_omitted(resource_info_factory):
    result = resource_info_factory("catalog.products")

    select_doc = result["common_parameters"]["select"]
    assert "select=-*,+id,+name" in select_doc
    assert "$meta.omitted" in select_doc


def test_resource_info_shows_enum_fields(resource_info_factory):
    result = resource_info_factory("catalog.products")

    assert result["enum_fields"] == {"status": ["Draft", "Published"]}
    assert result["filtering_tips"] == "Filter by status using RQL: eq(status,<value>)"
    assert result["example_queries"] == [
        "marketplace_query(resource='catalog.products', limit=10)",
        "marketplace_query(resource='catalog.products', rql='eq(status,Draft)', limit=10)",
    ]


def test_resource_info_shows_path_parameters(resource_info_factory):
    result = resource_info_factory("catalog.products.by_id")

    assert result["path_parameters"] == {
        "id": {"type": "string", "description": "Path parameter: id", "required": True}
    }
    assert result["path_params_required"] == "This resource requires path parameters: id=<value>"
    assert result["example_queries"][-1] == (
        "marketplace_query(resource='catalog.products.by_id', path_params={'id': '<id_value>'}, "
        "select='-*,+id,+name')"
    )


def test_resource_info_shows_children(resource_info_factory):
    result = resource_info_factory("catalog.products")

    children = result["related_resources"]["children"]
    assert [child["resource"] for child in children] == [
        "catalog.products.by_id",
        "catalog.products.by_id.items",
        "catalog.products.search",
    ]


def test_resource_info_shows_similar(resource_info_factory):
    result = resource_info_factory("catalog.products.by_id")

    assert result["related_resources"]["similar"] == [
        {"resource": "catalog.products.search", "summary": "Search products"}
    ]


def test_resource_info_shows_closest_parent(resource_info_factory):
    result = resource_info_factory("catalog.products.by_id.items")

    assert result["related_resources"]["parent"] == {
        "resource": "catalog.products.by_id",
        "summary": "Product by ID",
        "path": "/public/v1/catalog/products/{id}",
    }


def test_resource_info_without_related_resources(resource_info_factory):
    result = resource_info_factory("catalog.items")

    assert "related_resources" not in result
    assert "enum_fields" not in result
    assert "path_parameters" not in result
