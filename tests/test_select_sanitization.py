#!/usr/bin/env python3
"""
Test select sanitization in marketplace_query.

Verifies that:
1. _get_allowed_select_fields returns top-level property names from the resource's item schema.
2. _sanitize_select drops fields not in the allowed set and always adds id when missing.
3. execute_marketplace_query sends sanitized select (invalid fields dropped, id included).
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.mcp_tools import (
    _get_allowed_select_fields,
    _sanitize_select,
    execute_marketplace_query,
)


class TestGetAllowedSelectFields:
    """Test _get_allowed_select_fields."""

    def test_returns_empty_when_resource_not_in_registry(self):
        spec = {"paths": {}}
        registry = {"other.resource": {"path": "/public/v1/other"}}
        assert _get_allowed_select_fields(spec, registry, "commerce.orders") == set()

    def test_returns_empty_when_openapi_spec_empty(self):
        registry = {"commerce.orders": {"path": "/public/v1/commerce/orders"}}
        assert _get_allowed_select_fields({}, registry, "commerce.orders") == set()

    def test_returns_allowed_fields_from_list_response_schema(self):
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


class TestSanitizeSelect:
    """Test _sanitize_select."""

    def test_returns_none_for_none(self):
        assert _sanitize_select(None, set(), None) is None

    def test_returns_empty_string_unchanged(self):
        assert _sanitize_select("", {"id"}, None) == ""
        assert _sanitize_select("  ", {"id"}, None) == "  "

    def test_adds_id_when_missing_and_allowed_empty(self):
        # When allowed is empty we only add id (not status/name); order is canonical (id, status, name) then rest
        result = _sanitize_select("audit,status", set(), None)
        assert result == "id,status,audit"

    def test_adds_id_when_missing_and_allowed_non_empty(self):
        # Canonical order: id, status, name first when present, then rest
        result = _sanitize_select("audit,status", {"id", "audit", "status"}, None)
        assert result == "id,status,audit"

    def test_keeps_id_when_present(self):
        result = _sanitize_select("id,audit,status", {"id", "audit", "status"}, None)
        assert result == "id,status,audit"

    def test_drops_invalid_fields_and_adds_id(self):
        # orderNumber not in schema (e.g. commerce.orders has id, status, audit but not orderNumber)
        result = _sanitize_select(
            "audit,status,orderNumber",
            {"id", "audit", "status"},
            None,
        )
        assert result == "id,status,audit"
        assert "orderNumber" not in result

    def test_preserves_plus_prefix_for_rest(self):
        # Always-include fields (id, status, name) are output bare; other fields keep their + prefix when in rest
        result = _sanitize_select(
            "+audit,+status",
            {"id", "audit", "status"},
            None,
        )
        assert result.startswith("id,status,")
        assert "+audit" in result

    def test_top_level_validation_audit_dot_path(self):
        # audit.created.at -> top-level field is "audit"
        result = _sanitize_select(
            "audit.created.at,status",
            {"id", "audit", "status"},
            None,
        )
        assert "audit.created.at" in result
        assert "status" in result
        assert "id" in result

    def test_adds_id_status_name_when_in_schema_and_missing(self):
        # When schema has id, status, name we always add any that are missing
        result = _sanitize_select(
            "audit",
            {"id", "status", "name", "audit"},
            None,
        )
        assert result == "id,status,name,audit"

    def test_adds_only_status_and_name_when_id_already_present(self):
        result = _sanitize_select(
            "id,audit",
            {"id", "status", "name", "audit"},
            None,
        )
        assert "id" in result
        assert "status" in result
        assert "name" in result
        assert "audit" in result
        # Order: id, status, name first (added), then rest
        assert result.startswith("id,status,name,")


class TestExecuteMarketplaceQuerySelectSanitization:
    """Test that execute_marketplace_query applies select sanitization."""

    @pytest.fixture
    def api_client(self):
        client = Mock()
        client.get = AsyncMock()
        return client

    @pytest.fixture
    def endpoints_registry(self):
        return {
            "commerce.orders": {
                "path": "/public/v1/commerce/orders",
                "method": "GET",
            }
        }

    @pytest.fixture
    def openapi_spec(self):
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
    def mock_api_response(self):
        return {
            "data": [{"id": "ord-1", "status": "Created", "audit": {}}],
            "$meta": {"pagination": {"total": 1, "limit": 100, "offset": 0}},
        }

    @pytest.mark.asyncio
    async def test_sanitizes_select_drops_invalid_adds_id(self, api_client, endpoints_registry, openapi_spec, mock_api_response):
        """Select with orderNumber (invalid) is sanitized to allowed fields and id is added."""
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
    async def test_select_without_openapi_spec_adds_id(self, api_client, endpoints_registry, mock_api_response):
        """When openapi_spec is None, we still add id if missing (no field dropping)."""
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
