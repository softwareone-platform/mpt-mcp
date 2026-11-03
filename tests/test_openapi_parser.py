import pytest

from mpt_mcp.openapi_parser import OpenAPIParser

ORDERS_PATH = "/public/v1/commerce/orders"
PRODUCTS_PATH = "/public/v1/catalog/products"
TOKENS_PATH = "/public/v1/accounts/api-tokens"
SCHEMA_PROPERTY_LIMIT = 10


@pytest.fixture
def spec():
    return {
        "paths": {
            ORDERS_PATH: {
                "get": {
                    "summary": "List orders",
                    "description": "Orders of the account",
                    "parameters": [{"name": "limit", "in": "query"}],
                    "responses": {
                        "200": {
                            "description": "Orders",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "status": {
                                                            "type": "string",
                                                            "enum": ["Draft", "Completed"],
                                                            "example": "Draft",
                                                        }
                                                    },
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            PRODUCTS_PATH: {"get": {}, "post": {}},
            TOKENS_PATH: {"get": {}},
            "/public/v1/commerce/orders/{id}/complete": {"post": {}},
        }
    }


def test_extract_get_endpoints_only_get(spec):
    parser = OpenAPIParser()

    result = parser.extract_get_endpoints(spec)

    assert [endpoint["path"] for endpoint in result] == [ORDERS_PATH, PRODUCTS_PATH, TOKENS_PATH]


def test_extract_get_endpoints_reads_operation(spec):
    parser = OpenAPIParser()

    result = parser.extract_get_endpoints(spec)[0]

    assert result == {
        "path": ORDERS_PATH,
        "summary": "List orders",
        "description": "Orders of the account",
        "parameters": [{"name": "limit", "in": "query"}],
        "response": {
            "description": "Orders",
            "schema": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"status": {"type": "object", "description": "..."}},
                        },
                    }
                },
            },
        },
    }


def test_extract_get_endpoints_defaults_operation(spec):
    parser = OpenAPIParser()

    result = parser.extract_get_endpoints(spec)[1]

    assert result == {
        "path": PRODUCTS_PATH,
        "summary": f"GET {PRODUCTS_PATH}",
        "description": "",
        "parameters": [],
        "response": {},
    }


def test_extract_get_endpoints_keeps_enum():
    status = {"type": "string", "enum": ["Draft"], "example": "Draft", "description": "Status"}
    spec = {
        "paths": {
            ORDERS_PATH: {
                "get": {
                    "responses": {
                        "200": {"content": {"application/json": {"schema": status}}},
                    },
                },
            },
        },
    }
    parser = OpenAPIParser()

    result = parser.extract_get_endpoints(spec)

    assert result[0]["response"]["schema"] == status


def test_extract_get_endpoints_limits_properties():
    properties = {f"field{index}": {"type": "string"} for index in range(SCHEMA_PROPERTY_LIMIT + 2)}
    schema = {"type": "object", "properties": properties}
    spec = {
        "paths": {
            ORDERS_PATH: {
                "get": {"responses": {"200": {"content": {"application/json": {"schema": schema}}}}}
            }
        }
    }
    parser = OpenAPIParser()

    result = parser.extract_get_endpoints(spec)

    assert list(result[0]["response"]["schema"]["properties"]) == [
        f"field{index}" for index in range(SCHEMA_PROPERTY_LIMIT)
    ]


@pytest.mark.parametrize(
    ("include_patterns", "exclude_patterns", "expected"),
    [
        ("commerce, catalog", "", [ORDERS_PATH, PRODUCTS_PATH]),
        ("", "api-tokens", [ORDERS_PATH, PRODUCTS_PATH]),
        ("public", "catalog,accounts", [ORDERS_PATH]),
    ],
)
def test_extract_get_endpoints_filters_paths(spec, include_patterns, exclude_patterns, expected):
    parser = OpenAPIParser(include_patterns=include_patterns, exclude_patterns=exclude_patterns)

    result = parser.extract_get_endpoints(spec)

    assert [endpoint["path"] for endpoint in result] == expected
