import json

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.query.paths import fill_path_params, get_endpoint_path, suggest_resources


@pytest.fixture
def resources_registry():
    return {
        "catalog.products": {"path": "/public/v1/catalog/products"},
        "catalog.products.by_id": {"path": "/public/v1/catalog/products/{id}"},
        "commerce.orders": {"path": "/public/v1/commerce/orders"},
        "accounts.buyers": {"path": "/public/v1/accounts/buyers"},
    }


def test_get_endpoint_path(resources_registry):
    result = get_endpoint_path("catalog.products.by_id", resources_registry)

    assert result == "/public/v1/catalog/products/{id}"


def test_unknown_resource_suggests_similar(resources_registry):
    with pytest.raises(ToolError, match=r"Unknown resource: 'catalog\.product'") as error:
        get_endpoint_path("catalog.product", resources_registry)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert "catalog.products" in details["did_you_mean"]


def test_unknown_resource_shows_categories(resources_registry):
    with pytest.raises(ToolError) as error:
        get_endpoint_path("invalid.resource", resources_registry)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert sorted(details["available_categories"]) == ["accounts", "catalog", "commerce"]


@pytest.mark.parametrize(
    ("endpoint_path", "path_params", "expected"),
    [
        (
            "/public/v1/catalog/products/{id}",
            {"id": "PRD-1234-5678"},
            "/public/v1/catalog/products/PRD-1234-5678",
        ),
        (
            "/public/v1/commerce/orders/{orderId}/lines/{lineId}",
            {"orderId": "ORD-1234-5678", "lineId": "LIN-9876-5432"},
            "/public/v1/commerce/orders/ORD-1234-5678/lines/LIN-9876-5432",
        ),
        ("/public/v1/catalog/items", None, "/public/v1/catalog/items"),
        ("/public/v1/system/tasks/{id}", {"id": 12345}, "/public/v1/system/tasks/12345"),
    ],
)
def test_fill_path_params(endpoint_path, path_params, expected):
    result = fill_path_params("test.resource", endpoint_path, path_params)

    assert result == expected


def test_missing_path_params_hint():
    with pytest.raises(ToolError) as error:
        fill_path_params(
            "commerce.orders.lines",
            "/public/v1/commerce/orders/{orderId}/lines/{lineId}",
            {"orderId": "ORD-1234-5678"},
        )

    message, details = str(error.value).split("\n", 1)
    assert message == "This resource requires path parameters: lineId"
    assert "'lineId': 'LIN-1234-5678'" in json.loads(details)["hint"]


@pytest.mark.parametrize(
    ("endpoint_path", "resource", "expected_example"),
    [
        (
            "/public/v1/catalog/products/{id}",
            "catalog.products.by_id",
            (
                "marketplace_query(resource='catalog.products.by_id', "
                "path_params={'id': 'PRD-1234-5678'}, limit=10)"
            ),
        ),
        (
            "/public/v1/commerce/orders/{orderId}",
            "commerce.orders.by_id",
            (
                "marketplace_query(resource='commerce.orders.by_id', "
                "path_params={'orderId': 'ORD-1234-5678-9012'}, limit=10)"
            ),
        ),
    ],
)
def test_missing_path_params_shows_example(endpoint_path, resource, expected_example):
    with pytest.raises(ToolError, match="requires path parameters") as error:
        fill_path_params(resource, endpoint_path, None)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["example"] == expected_example
    assert "hint" in details


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
