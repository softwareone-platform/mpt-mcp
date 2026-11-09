import pytest

from mpt_mcp.marketplace.schemas import (
    get_get_operation,
    get_item_schema,
    get_response_item_schema,
    get_response_schema,
    resolve_ref,
    resolve_schema,
)

ORDERS_PATH = "/public/v1/commerce/orders"


@pytest.fixture
def orders_spec():
    order = {"type": "object", "properties": {"id": {"type": "string"}}}
    list_schema = {
        "properties": {"data": {"type": "array", "items": {"$ref": "#/components/schemas/Order"}}}
    }
    response = {
        "200": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderList"}}}
        }
    }
    return {
        "components": {"schemas": {"Order": order, "OrderList": list_schema}},
        "paths": {ORDERS_PATH: {"get": {"responses": response}}, "/public/v1/empty": {"post": {}}},
    }


def test_get_get_operation(orders_spec):
    result = get_get_operation(orders_spec, ORDERS_PATH)

    assert result is orders_spec["paths"][ORDERS_PATH]["get"]


@pytest.mark.parametrize("path", ["/public/v1/empty", "/public/v1/missing"])
def test_get_get_operation_missing(orders_spec, path):
    result = get_get_operation(orders_spec, path)

    assert result is None


def test_get_response_schema_resolves_ref(orders_spec):
    result = get_response_schema(orders_spec, orders_spec["paths"][ORDERS_PATH]["get"])

    assert result == orders_spec["components"]["schemas"]["OrderList"]


@pytest.mark.parametrize(
    "operation",
    [
        {},
        {"responses": {"404": {}}},
        {"responses": {"200": {"content": {"text/html": {"schema": {}}}}}},
        {"responses": {"200": {"content": {"application/json": {}}}}},
    ],
)
def test_get_response_schema_missing(operation):
    result = get_response_schema({}, operation)

    assert result is None


def test_get_response_item_schema_unwraps_list(orders_spec):
    registry = {"commerce.orders": {"path": ORDERS_PATH}}

    result = get_response_item_schema(orders_spec, registry, "commerce.orders")

    assert result == orders_spec["components"]["schemas"]["Order"]


@pytest.mark.parametrize(
    ("registry", "resource"),
    [
        ({}, "commerce.orders"),
        ({"commerce.orders": {}}, "commerce.orders"),
        ({"empty": {"path": "/public/v1/empty"}}, "empty"),
    ],
)
def test_get_response_item_schema_missing(orders_spec, registry, resource):
    result = get_response_item_schema(orders_spec, registry, resource)

    assert result == {}


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("#/components/schemas/Order", {"type": "object"}),
        ("#/components/schemas/Missing", {}),
        ("other.json#/Order", {}),
        ("", {}),
    ],
)
def test_resolve_ref(ref, expected):
    spec = {"components": {"schemas": {"Order": {"type": "object"}}}}

    result = resolve_ref(spec, ref)

    assert result == expected


def test_resolve_schema_follows_ref_and_all_of():
    spec = {"components": {"schemas": {"Order": {"properties": {"id": {}}}}}}

    result = resolve_schema(spec, {"allOf": [{"$ref": "#/components/schemas/Order"}]})

    assert result == {"properties": {"id": {}}}


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array", "items": {"$ref": "#/components/schemas/Order"}},
        {"type": "object", "properties": {"data": {"type": "array", "items": {"id": 1}}}},
        {"properties": {"results": {"type": "array", "items": {"id": 1}}}},
    ],
)
def test_get_item_schema_unwraps_lists(schema):
    spec = {"components": {"schemas": {"Order": {"id": 1}}}}

    result = get_item_schema(spec, schema)

    assert result == {"id": 1}


def test_get_item_schema_keeps_object_schema():
    schema = {"type": "object", "properties": {"id": {"type": "string"}}}

    result = get_item_schema({}, schema)

    assert result == schema
