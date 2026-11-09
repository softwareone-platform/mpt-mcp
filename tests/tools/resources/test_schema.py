import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.resources.schema import describe_resource_schema

ORDERS_PATH = "/public/v1/commerce/orders"


@pytest.fixture
def orders_openapi_spec():
    order_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Order ID", "example": "ORD-1"},
            "status": {"type": "string", "enum": ["Draft", "Completed"]},
            "audit": {"allOf": [{"$ref": "#/components/schemas/Audit"}]},
            "lines": {"type": "array"},
        },
    }
    list_schema = {"properties": {"data": {"type": "array", "items": {"$ref": "#/order"}}}}
    response = {"200": {"content": {"application/json": {"schema": list_schema}}}}
    audit_schema = {"properties": {"created": {"type": "object", "description": "Creation"}}}
    return {
        "order": order_schema,
        "components": {"schemas": {"Audit": audit_schema}},
        "paths": {ORDERS_PATH: {"get": {"summary": "List orders", "responses": response}}},
    }


@pytest.fixture
def resource_schema_factory(spec_factory, orders_openapi_spec):
    def factory(openapi_spec=None, endpoint_path=ORDERS_PATH):
        spec = spec_factory(openapi_spec=openapi_spec or orders_openapi_spec)
        return describe_resource_schema("commerce.orders", endpoint_path, spec).model_dump()

    return factory


def test_resource_schema_lists_item_fields(resource_schema_factory):
    result = resource_schema_factory()

    assert list(result["fields"]) == ["id", "status", "audit", "lines"]
    assert result["summary"] == "List orders"


def test_resource_schema_describes_fields(resource_schema_factory):
    result = resource_schema_factory()

    fields = result["fields"]
    assert fields["id"] == {"type": "string", "description": "Order ID", "example": "ORD-1"}
    assert fields["status"]["valid_values"] == ["Draft", "Completed"]
    assert fields["audit"]["type"] == "object"
    assert fields["audit"]["nested_fields"] == {
        "created": {"type": "object", "description": "Creation"}
    }


def test_resource_schema_builds_filtering_hints(resource_schema_factory):
    result = resource_schema_factory()

    assert result["filtering_hints"] == {
        "simple_filters": ["eq(id,value)", "eq(status,value)"],
        "search_fields": ["ilike(id,*keyword*)", "ilike(status,*keyword*)"],
        "enum_filters": ["eq(status,Draft)"],
    }


def test_resource_schema_without_response_schema(resource_schema_factory):
    openapi_spec = {"paths": {ORDERS_PATH: {"get": {"responses": {}}}}}

    result = resource_schema_factory(openapi_spec=openapi_spec)

    assert "response_schema" not in result
    assert "fields" not in result
    assert "filtering_hints" not in result
    assert result["common_queries"]["basic"] == "commerce.orders?limit=10"


@pytest.mark.parametrize(
    ("openapi_spec", "expected_error"),
    [
        ({"paths": {}}, f"Path {ORDERS_PATH} not found in OpenAPI spec"),
        ({"paths": {ORDERS_PATH: {"post": {}}}}, f"GET operation not found for {ORDERS_PATH}"),
    ],
)
def test_resource_schema_missing_operation(resource_schema_factory, openapi_spec, expected_error):
    with pytest.raises(ToolError, match=expected_error):
        resource_schema_factory(openapi_spec=openapi_spec)
