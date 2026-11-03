import re

import pytest

from mpt_mcp.audit_fields import (
    FALLBACK_STATIC_REGEX,
    build_audit_regex,
    collect_audit_events_and_paths_from_props,
    get_audit_data_from_spec,
    get_audit_fields,
    get_audit_regex,
    get_item_schema,
    resolve_ref,
    resolve_schema,
    update_cache,
)
from mpt_mcp.endpoint_registry import path_to_resource_id


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


@pytest.fixture
def cache_key(request):
    return f"https://{request.node.name}.example.com"


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


def test_collect_audit_events_and_paths():
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

    result = collect_audit_events_and_paths_from_props({}, properties)

    events, paths = result
    assert events == {"created", "updated"}
    assert [audit_path["path"] for audit_path in paths] == [
        "audit.created.at",
        "audit.created.by",
        "audit.updated.at",
    ]


def test_get_audit_data_from_spec(audit_spec):
    result = get_audit_data_from_spec(audit_spec, path_to_resource_id)

    assert result == {
        "events": {"created", "failed"},
        "by_resource": {
            "commerce.orders": ["created", "failed"],
            "commerce.orders.by_id": ["created", "failed"],
        },
    }


def test_build_audit_regex_matches_spec_events():
    result = build_audit_regex({"failed", "created"})

    assert result.pattern == r"audit\.(created|failed)\.(at|by)"
    assert result.search("gt(audit.failed.at,2026-01-01)")


def test_build_audit_regex_without_events():
    result = build_audit_regex(set())

    assert result is FALLBACK_STATIC_REGEX


def test_update_cache_stores_spec_audit_data(audit_spec, cache_key):
    update_cache(cache_key, audit_spec, path_to_resource_id)  # act

    assert get_audit_regex(cache_key) == re.compile(r"audit\.(created|failed)\.(at|by)")
    assert get_audit_fields(cache_key) == {
        "by_resource": {
            "commerce.orders": ["created", "failed"],
            "commerce.orders.by_id": ["created", "failed"],
        }
    }


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("commerce.orders", {"resource": "commerce.orders", "events": ["created", "failed"]}),
        (
            "catalog.products",
            {
                "resource": "catalog.products",
                "events": [],
                "hint": "No audit fields found for this resource",
            },
        ),
    ],
)
def test_get_audit_fields_for_resource(audit_spec, cache_key, resource, expected):
    update_cache(cache_key, audit_spec, path_to_resource_id)

    result = get_audit_fields(cache_key, resource)

    assert result == expected


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        (None, {"by_resource": {}}),
        (
            "commerce.orders",
            {
                "error": "Audit fields not available (spec not loaded)",
                "resource": "commerce.orders",
            },
        ),
    ],
)
def test_get_audit_fields_without_spec(cache_key, resource, expected):
    result = get_audit_fields(cache_key, resource)

    assert result == expected


def test_get_audit_regex_falls_back_without_spec(cache_key):
    result = get_audit_regex(cache_key)

    assert result is FALLBACK_STATIC_REGEX
