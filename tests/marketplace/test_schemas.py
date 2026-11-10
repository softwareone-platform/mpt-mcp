import pytest

from mpt_mcp.marketplace.schemas import OpenAPISpec

ORDERS_PATH = "/public/v1/commerce/orders"


@pytest.fixture
def orders_document():
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


@pytest.fixture
def orders_spec(orders_document):
    return OpenAPISpec(orders_document)


def test_get_operation(orders_spec, orders_document):
    result = orders_spec.get_operation(ORDERS_PATH)

    assert result is orders_document["paths"][ORDERS_PATH]["get"]


def test_get_operation_of_method(orders_spec):
    result = orders_spec.get_operation("/public/v1/empty", method="post")

    assert result == {}


@pytest.mark.parametrize("path", ["/public/v1/empty", "/public/v1/missing"])
def test_get_operation_missing(orders_spec, path):
    result = orders_spec.get_operation(path)

    assert result is None


def test_get_response_schema_resolves_ref(orders_spec, orders_document):
    result = orders_spec.get_response_schema(orders_document["paths"][ORDERS_PATH]["get"])

    assert result == orders_document["components"]["schemas"]["OrderList"]


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
    result = OpenAPISpec({}).get_response_schema(operation)

    assert result is None


def test_get_response_item_schema_unwraps_list(orders_spec, orders_document):
    result = orders_spec.get_response_item_schema(ORDERS_PATH)

    assert result == orders_document["components"]["schemas"]["Order"]


@pytest.mark.parametrize("path", ["/public/v1/empty", "/public/v1/missing"])
def test_get_response_item_schema_missing(orders_spec, path):
    result = orders_spec.get_response_item_schema(path)

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
    spec = OpenAPISpec({"components": {"schemas": {"Order": {"type": "object"}}}})

    result = spec.resolve_ref(ref)

    assert result == expected


def test_resolve_schema_follows_ref_and_all_of():
    order = {"properties": {"id": {}}}
    spec = OpenAPISpec({"components": {"schemas": {"Order": order}}})

    result = spec.resolve_schema({"allOf": [{"$ref": "#/components/schemas/Order"}]})

    assert result == order


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array", "items": {"$ref": "#/components/schemas/Order"}},
        {"type": "object", "properties": {"data": {"type": "array", "items": {"id": 1}}}},
        {"properties": {"results": {"type": "array", "items": {"id": 1}}}},
    ],
)
def test_get_item_schema_unwraps_lists(schema):
    spec = OpenAPISpec({"components": {"schemas": {"Order": {"id": 1}}}})

    result = spec.get_item_schema(schema)

    assert result == {"id": 1}


def test_get_item_schema_keeps_object_schema():
    schema = {"type": "object", "properties": {"id": {"type": "string"}}}

    result = OpenAPISpec({}).get_item_schema(schema)

    assert result == schema


def test_document_properties():
    document = {"openapi": "3.1.0", "info": {"title": "API"}, "paths": {ORDERS_PATH: {}}}
    spec = OpenAPISpec(document)

    result = (spec.version, spec.api_info, spec.paths)

    assert result == ("3.1.0", {"title": "API"}, {ORDERS_PATH: {}})


def test_document_properties_default():
    spec = OpenAPISpec({})

    result = (spec.version, spec.api_info, spec.paths)

    assert result == ("3.0", {}, {})
