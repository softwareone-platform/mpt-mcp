import json

import pytest
from fastmcp.exceptions import ToolError


@pytest.fixture
def resources_spec(spec_factory, openapi_spec):
    return spec_factory(
        registry={
            "catalog.products": {"path": "/public/v1/catalog/products"},
            "catalog.products.by_id": {"path": "/public/v1/catalog/products/{id}"},
            "commerce.orders": {"path": "/public/v1/commerce/orders"},
            "accounts.buyers": {"path": "/public/v1/accounts/buyers"},
        },
        openapi_spec=openapi_spec,
    )


def test_get_categories(resources_spec):
    result = resources_spec.get_categories()

    assert result == ["accounts", "catalog", "commerce"]


def test_get_endpoint(resources_spec):
    result = resources_spec.get_endpoint("catalog.products.by_id")

    assert result == {"path": "/public/v1/catalog/products/{id}"}


def test_unknown_resource_suggests_similar(resources_spec):
    with pytest.raises(ToolError, match=r"Unknown resource: 'catalog\.product'") as error:
        resources_spec.get_endpoint("catalog.product")

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert "catalog.products" in details["did_you_mean"]


def test_unknown_resource_shows_categories(resources_spec):
    with pytest.raises(ToolError) as error:
        resources_spec.get_endpoint("invalid.resource")

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["available_categories"] == ["accounts", "catalog", "commerce"]


def test_get_item_schema(resources_spec):
    result = resources_spec.get_item_schema("commerce.orders")

    assert result["type"] == "object"
    assert list(result["properties"]) == ["id", "status", "audit"]


@pytest.mark.parametrize("resource", ["catalog.products", "unknown.resource"])
def test_get_item_schema_missing(resources_spec, resource):
    result = resources_spec.get_item_schema(resource)

    assert result == {}


def test_get_item_fields(resources_spec):
    result = resources_spec.get_item_fields("commerce.orders")

    assert result == {"id", "status", "audit"}


@pytest.fixture
def suggestions_factory(spec_factory):
    def factory(resource_names, resource):
        registry = {resource_name: {"path": "/public/v1/x"} for resource_name in resource_names}
        spec = spec_factory(registry=registry)
        with pytest.raises(ToolError) as error:
            spec.get_endpoint(resource)
        _, error_details = str(error.value).split("\n", 1)
        return json.loads(error_details).get("did_you_mean", [])

    return factory


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("catalog.product", ["catalog.products"]),
        ("catalog.prodcts", ["catalog.products"]),
        ("Commerce.Orders", ["commerce.orders"]),
        ("billing.unknown", []),
    ],
)
def test_unknown_resource_suggestions(suggestions_factory, resource, expected):
    result = suggestions_factory(
        ["catalog.products", "commerce.orders", "accounts.buyers"], resource
    )

    assert result == expected


def test_suggestions_containing_first(suggestions_factory):
    resource_names = [f"catalog.products.item{index}" for index in range(6)] + ["catalog.producs"]

    result = suggestions_factory(resource_names, "catalog.products")

    assert result == [f"catalog.products.item{index}" for index in range(5)]


def test_suggestions_closest_first(suggestions_factory):
    resource_names = [f"public-catalog.product-profiles.item{index}" for index in range(6)]
    resource_names.append("catalog.products")

    result = suggestions_factory(resource_names, "catalog.product")

    assert result[0] == "catalog.products"
