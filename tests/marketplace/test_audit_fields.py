import pytest

from mpt_mcp.marketplace.audit_fields import (
    FALLBACK_STATIC_REGEX,
    build_audit_regex,
    collect_audit_events,
    get_audit_data_from_spec,
)
from mpt_mcp.marketplace.endpoint_registry import path_to_resource_id
from mpt_mcp.marketplace.schemas import OpenAPISpec


@pytest.fixture
def audit_spec():
    event_fields = {"at": {"type": "string"}, "by": {"type": "object"}}
    event = {"type": "object", "properties": event_fields}
    return {
        "paths": {
            "/public/v1/commerce/orders": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/OrderList"}
                                }
                            }
                        }
                    }
                }
            },
            "/public/v1/commerce/orders/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Order"}
                                }
                            }
                        }
                    }
                }
            },
            "/public/v1/catalog/products": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "properties": {"id": {}}}
                                }
                            }
                        }
                    }
                },
                "post": {},
            },
        },
        "components": {
            "schemas": {
                "OrderList": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "array", "items": {"$ref": "#/components/schemas/Order"}}
                    },
                },
                "Order": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "audit": {"$ref": "#/components/schemas/OrderAudit"},
                    },
                },
                "OrderAudit": {
                    "type": "object",
                    "properties": {"created": event, "failed": event},
                },
            }
        },
    }


def test_collect_audit_events():
    properties = {
        "orderAudit": {
            "properties": {
                "created": {"properties": {"timestamp": {}, "actor": {}}},
                "updated": {"properties": {"date": {}}},
                "deleted": {"properties": {"reason": {}}},
            }
        },
        "name": {"type": "string"},
    }

    result = collect_audit_events(OpenAPISpec({}), properties)

    assert result == {"created", "updated"}


def test_get_audit_data_from_spec(audit_spec):
    result = get_audit_data_from_spec(OpenAPISpec(audit_spec), path_to_resource_id)

    assert result == {
        "events": {"created", "failed"},
        "by_resource": {
            "commerce.orders": ["created", "failed"],
            "commerce.orders.by_id": ["created", "failed"],
        },
    }


def test_collect_skips_audit_props_without_schema():
    properties = {"audit": "not a schema", "lineAudit": {"properties": {"created": "x"}}}

    result = collect_audit_events(OpenAPISpec({}), properties)

    assert result == set()


@pytest.mark.parametrize("path_item", [{"post": {}}, {"get": {"responses": {}}}])
def test_audit_data_skips_paths_without_response(path_item):
    spec = OpenAPISpec({"paths": {"/public/v1/commerce/orders": path_item}})

    result = get_audit_data_from_spec(spec, path_to_resource_id)

    assert result == {"events": set(), "by_resource": {}}


@pytest.mark.parametrize(
    "item_properties",
    [{}, {"id": {"type": "string"}}, {"audit": {"properties": {"created": {}}}}],
)
def test_audit_data_skips_items_without_events(item_properties):
    item_schema = {"type": "object", "properties": item_properties}
    response = {"200": {"content": {"application/json": {"schema": item_schema}}}}
    spec = OpenAPISpec({"paths": {"/public/v1/commerce/orders": {"get": {"responses": response}}}})

    result = get_audit_data_from_spec(spec, path_to_resource_id)

    assert result == {"events": set(), "by_resource": {}}


def test_build_audit_regex_matches_spec_events():
    result = build_audit_regex({"failed", "created"})

    assert result.pattern == r"audit\.(created|failed)\.(at|by)"
    assert result.search("gt(audit.failed.at,2026-01-01)")


def test_build_audit_regex_without_events():
    result = build_audit_regex(set())

    assert result is FALLBACK_STATIC_REGEX


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("audit.created.at", True),
        ("audit.updated.at", True),
        ("audit.completed.at", True),
        ("audit.processing.at", True),
        ("audit.quoted.at", True),
        ("audit.failed.at", True),
        ("audit.created.by", True),
        ("audit.quoted.by", True),
        ("audit.created.by.id", True),  # matches the prefix
        ("status", False),
        ("created.at", False),
        ("audit.status", False),
        ("audit.created", False),
    ],
)
def test_fallback_audit_regex_matches_fields(field, expected):
    result = FALLBACK_STATIC_REGEX.search(field) is not None

    assert result is expected
