#!/usr/bin/env python3

from unittest.mock import AsyncMock, Mock

import pytest

from mpt_mcp.mcp_tools import (
    _get_allowed_select_fields,
    _sanitize_select,
    execute_marketplace_query,
)


def test_returns_empty_when_resource_not_in_registry():
    spec = {"paths": {}}
    registry = {"other.resource": {"path": "/public/v1/other"}}
    assert _get_allowed_select_fields(spec, registry, "commerce.orders") == set()


def test_returns_empty_when_openapi_spec_empty():
    registry = {"commerce.orders": {"path": "/public/v1/commerce/orders"}}
    assert _get_allowed_select_fields({}, registry, "commerce.orders") == set()


def test_returns_allowed_fields_from_list_response_schema():
    # Minimal spec: list endpoint with data[] items schema (marketplace style)
    spec = {
        "paths": {
            "/public/v1/commerce/orders": {
                "get": {
                    "responses": {
                        "200": {
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
                                                        "id": {"type": "string"},
                                                        "status": {"type": "string"},
                                                        "audit": {"type": "object"},
                                                    },
                                                },
                                            },
                                            "$meta": {"type": "object"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    registry = {"commerce.orders": {"path": "/public/v1/commerce/orders"}}
    allowed = _get_allowed_select_fields(spec, registry, "commerce.orders")
    assert allowed == {"id", "status", "audit"}
    assert "orderNumber" not in allowed


def test_returns_none_for_none():
    assert _sanitize_select(None, set()) is None


def test_returns_empty_string_unchanged():
    assert _sanitize_select("", {"id"}) == ""
    assert _sanitize_select("  ", {"id"}) == "  "


def test_adds_id_when_missing_and_allowed_empty():
    # When allowed is empty we only add id (not status/name); order is canonical (id, status, name) then rest
    result = _sanitize_select("audit,status", set())
    assert result == "id,status,audit"


def test_adds_id_when_missing_and_allowed_non_empty():
    # Canonical order: id, status, name first when present, then rest
    result = _sanitize_select("audit,status", {"id", "audit", "status"})
    assert result == "id,status,audit"


def test_keeps_id_when_present():
    result = _sanitize_select("id,audit,status", {"id", "audit", "status"})
    assert result == "id,status,audit"


def test_drops_invalid_fields_and_adds_id():
    # orderNumber not in schema (e.g. commerce.orders has id, status, audit but not orderNumber)
    result = _sanitize_select("audit,status,orderNumber", {"id", "audit", "status"})
    assert result == "id,status,audit"
    assert "orderNumber" not in result


def test_preserves_plus_prefix_for_rest():
    # Always-include fields (id, status, name) are output bare; other fields keep their + prefix when in rest
    result = _sanitize_select("+audit,+status", {"id", "audit", "status"})
    assert result.startswith("id,status,")
    assert "+audit" in result


def test_top_level_validation_audit_dot_path():
    # audit.created.at -> top-level field is "audit"
    result = _sanitize_select("audit.created.at,status", {"id", "audit", "status"})
    assert "audit.created.at" in result
    assert "status" in result
    assert "id" in result


def test_adds_id_status_name_when_in_schema_and_missing():
    # When schema has id, status, name we always add any that are missing
    result = _sanitize_select("audit", {"id", "status", "name", "audit"})
    assert result == "id,status,name,audit"


def test_adds_only_status_and_name_when_id_already_present():
    result = _sanitize_select("id,audit", {"id", "status", "name", "audit"})
    assert "id" in result
    assert "status" in result
    assert "name" in result
    assert "audit" in result
    # Order: id, status, name first (added), then rest
    assert result.startswith("id,status,name,")


@pytest.fixture
def api_client():
    client = Mock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def endpoints_registry():
    return {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "method": "GET",
        }
    }


@pytest.fixture
def openapi_spec():
    return {
        "paths": {
            "/public/v1/commerce/orders": {
                "get": {
                    "responses": {
                        "200": {
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
                                                        "id": {"type": "string"},
                                                        "status": {"type": "string"},
                                                        "audit": {"type": "object"},
                                                    },
                                                },
                                            },
                                            "$meta": {"type": "object"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }


@pytest.fixture
def mock_api_response():
    return {
        "data": [{"id": "ord-1", "status": "Created", "audit": {}}],
        "$meta": {"pagination": {"total": 1, "limit": 100, "offset": 0}},
    }


@pytest.mark.asyncio
async def test_sanitizes_select_drops_invalid_adds_id(api_client, endpoints_registry, openapi_spec, mock_api_response):
    api_client.get.return_value = mock_api_response

    await execute_marketplace_query(
        resource="commerce.orders",
        rql="",
        limit=10,
        offset=None,
        page=None,
        select="audit,status,orderNumber",  # orderNumber not in schema
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
        openapi_spec=openapi_spec,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "select" in params
    # orderNumber must be dropped; id must be present
    assert "orderNumber" not in params["select"]
    assert "id" in params["select"]
    assert "audit" in params["select"]
    assert "status" in params["select"]


@pytest.mark.asyncio
async def test_select_without_openapi_spec_adds_id(api_client, endpoints_registry, mock_api_response):
    api_client.get.return_value = mock_api_response

    await execute_marketplace_query(
        resource="commerce.orders",
        rql="",
        limit=10,
        offset=None,
        page=None,
        select="audit,status",
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
        openapi_spec=None,
    )

    params = api_client.get.call_args.kwargs.get("params", {})
    assert "select" in params
    assert "id" in params["select"]
    assert "audit" in params["select"]
    assert "status" in params["select"]
