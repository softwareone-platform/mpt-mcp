import json

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.endpoints import get_endpoint, suggest_resources


@pytest.fixture
def resources_registry():
    return {
        "catalog.products": {"path": "/public/v1/catalog/products"},
        "catalog.products.by_id": {"path": "/public/v1/catalog/products/{id}"},
        "commerce.orders": {"path": "/public/v1/commerce/orders"},
        "accounts.buyers": {"path": "/public/v1/accounts/buyers"},
    }


def test_get_endpoint(resources_registry):
    result = get_endpoint("catalog.products.by_id", resources_registry)

    assert result == {"path": "/public/v1/catalog/products/{id}"}


def test_unknown_resource_suggests_similar(resources_registry):
    with pytest.raises(ToolError, match=r"Unknown resource: 'catalog\.product'") as error:
        get_endpoint("catalog.product", resources_registry)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert "catalog.products" in details["did_you_mean"]


def test_unknown_resource_shows_categories(resources_registry):
    with pytest.raises(ToolError) as error:
        get_endpoint("invalid.resource", resources_registry)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["available_categories"] == ["accounts", "catalog", "commerce"]


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("catalog.product", ["catalog.products"]),
        ("catalog.prodcts", ["catalog.products"]),
        ("Commerce.Orders", ["commerce.orders"]),
        ("billing.unknown", []),
    ],
)
def test_suggest_resources(resource, expected):
    resources = ["catalog.products", "commerce.orders", "accounts.buyers"]

    result = suggest_resources(resource, resources)

    assert result == expected


def test_suggest_resources_containing_first():
    resources = [f"catalog.products.item{index}" for index in range(6)] + ["catalog.producs"]

    result = suggest_resources("catalog.products", resources)

    assert result == [f"catalog.products.item{index}" for index in range(5)]


def test_suggest_resources_closest_first():
    resources = [f"public-catalog.product-profiles.item{index}" for index in range(6)]
    resources.append("catalog.products")

    result = suggest_resources("catalog.product", resources)

    assert result[0] == "catalog.products"
