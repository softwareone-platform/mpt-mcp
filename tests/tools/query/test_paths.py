import json

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.query.paths import fill_path_params


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
