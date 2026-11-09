import re

import pytest

# The tests cover most of the module's functions, so they import them by name
from mpt_mcp.marketplace.audit_fields import (  # noqa: WPS235
    FALLBACK_STATIC_REGEX,
    build_audit_regex,
    collect_audit_events_and_paths_from_props,
    get_audit_data_from_spec,
    get_audit_fields,
    get_audit_regex,
    update_cache,
)
from mpt_mcp.marketplace.endpoint_registry import path_to_resource_id


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
    test_name = request.node.name
    return f"https://{test_name}.example.com"


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
