#!/usr/bin/env python3
"""
Test audit field auto-detection feature.

Verifies that the MCP server automatically adds `select=audit` when:
1. RQL queries use audit fields (e.g., audit.created.at, audit.updated.at)
2. Order parameters use audit fields (e.g., -audit.created.at)
3. The select parameter doesn't already include audit

This ensures users don't need to manually add select=audit when filtering/sorting by audit fields.
"""

import re
from unittest.mock import AsyncMock, Mock

import pytest

from src.mcp_tools import execute_marketplace_query


class TestAuditFieldAutoDetection:
    """Test automatic audit field detection and select parameter injection"""

    @pytest.fixture
    def api_client(self):
        """Create a mock API client"""
        client = Mock()
        client.get = AsyncMock()
        return client

    @pytest.fixture
    def endpoints_registry(self):
        """Create a mock endpoints registry"""
        return {
            "commerce.orders": {
                "path": "/public/v1/commerce/orders",
                "method": "GET",
            }
        }

    @pytest.fixture
    def mock_api_response(self):
        """Mock API response with audit fields"""
        return {
            "data": [
                {
                    "id": "ORD-123",
                    "status": "Completed",
                    "audit": {
                        "created": {"at": "2026-01-22T10:00:00Z", "by": {"id": "USR-1", "name": "User 1"}},
                        "updated": {"at": "2026-01-22T11:00:00Z", "by": {"id": "USR-2", "name": "User 2"}},
                    },
                }
            ],
            "$meta": {"pagination": {"total": 1, "limit": 10, "offset": 0}},
        }

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_filtering_by_created_at(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when filtering by audit.created.at"""
        api_client.get.return_value = mock_api_response

        rql = 'gt(audit.created.at,"2026-01-22T00:00:00Z")'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        # Verify API was called with select=audit
        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit'"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_filtering_by_updated_at(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when filtering by audit.updated.at"""
        api_client.get.return_value = mock_api_response

        rql = 'lt(audit.updated.at,"2026-01-22T23:59:59Z")'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit'"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_filtering_by_completed_at(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when filtering by audit.completed.at"""
        api_client.get.return_value = mock_api_response

        rql = 'gte(audit.completed.at,"2026-01-22T00:00:00Z")'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit'"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_filtering_by_processing_at(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when filtering by audit.processing.at"""
        api_client.get.return_value = mock_api_response

        rql = 'eq(audit.processing.at,"2026-01-22T10:00:00Z")'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit'"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_filtering_by_quoted_at(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when filtering by audit.quoted.at"""
        api_client.get.return_value = mock_api_response

        rql = 'lte(audit.quoted.at,"2026-01-22T23:59:59Z")'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit'"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_filtering_by_created_by(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when filtering by audit.created.by"""
        api_client.get.return_value = mock_api_response

        rql = 'eq(audit.created.by.id,"USR-123")'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit'"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_ordering_by_audit_field(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when ordering by audit fields"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql=None,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order="-audit.created.at",
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit' when ordering by audit field"

    @pytest.mark.asyncio
    async def test_auto_adds_audit_when_ordering_ascending_by_audit_field(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added when ordering ascending by audit fields"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql=None,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order="+audit.updated.at",
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit' when ordering by audit field"

    @pytest.mark.asyncio
    async def test_does_not_add_audit_when_already_in_select(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is NOT added again if already in select parameter"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='gt(audit.created.at,"2026-01-22T00:00:00Z")',
            limit=10,
            offset=None,
            page=None,
            select="audit,+id,+name",
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")
        # Count occurrences of 'audit' - should be exactly 1
        audit_count = select_value.count("audit")
        assert audit_count == 1, f"audit should appear exactly once in select, but found {audit_count} times: {select_value}"

    @pytest.mark.asyncio
    async def test_does_not_add_audit_when_using_plus_prefix(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is NOT added again if already in select with + prefix"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='gt(audit.created.at,"2026-01-22T00:00:00Z")',
            limit=10,
            offset=None,
            page=None,
            select="+audit,+id,+name",
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")
        audit_count = select_value.count("audit")
        assert audit_count == 1, f"audit should appear exactly once in select, but found {audit_count} times: {select_value}"

    @pytest.mark.asyncio
    async def test_does_not_add_audit_when_using_audit_dot_notation(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is NOT added again if already in select with audit.field notation"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='gt(audit.created.at,"2026-01-22T00:00:00Z")',
            limit=10,
            offset=None,
            page=None,
            select="+audit.created.at,+id,+name",
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")
        # Should not have standalone 'audit' added, but audit.created.at should be there
        assert "audit.created.at" in select_value, "audit.created.at should be in select"
        # Should not have standalone 'audit' added when audit.field is already present
        select_parts = [s.strip() for s in select_value.split(",")]
        standalone_audit = [p for p in select_parts if p == "audit" or p == "+audit"]
        assert len(standalone_audit) == 0, "standalone 'audit' should not be added when audit.field is already present"

    @pytest.mark.asyncio
    async def test_complex_rql_with_audit_fields(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is auto-added in complex RQL queries with audit fields"""
        api_client.get.return_value = mock_api_response

        rql = 'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),lt(audit.created.at,"2026-01-22T23:59:59Z"))'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=10,
            offset=None,
            page=None,
            select=None,
            order="-audit.created.at",
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        assert "audit" in params.get("select", ""), "select parameter should include 'audit' for complex RQL with audit fields"

    @pytest.mark.asyncio
    async def test_does_not_add_audit_when_no_audit_fields_used(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is NOT added when no audit fields are used in RQL or order"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='eq(status,"Completed")',
            limit=10,
            offset=None,
            page=None,
            select=None,
            order="-status",
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")
        assert "audit" not in select_value, "select parameter should NOT include 'audit' when no audit fields are used"

    @pytest.mark.asyncio
    async def test_appends_audit_to_existing_select(self, api_client, mock_api_response, endpoints_registry):
        """Test that audit is appended to existing select fields"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='gt(audit.created.at,"2026-01-22T00:00:00Z")',
            limit=10,
            offset=None,
            page=None,
            select="+id,+name,+status",
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")
        assert "audit" in select_value, "select should include 'audit'"
        assert "+id" in select_value, "select should still include original fields"
        assert "+name" in select_value, "select should still include original fields"
        assert "+status" in select_value, "select should still include original fields"

    @pytest.mark.asyncio
    async def test_creates_select_with_audit_when_no_select_provided(self, api_client, mock_api_response, endpoints_registry):
        """Test that select=audit is created when no select parameter is provided"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='gt(audit.created.at,"2026-01-22T00:00:00Z")',
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")
        assert select_value == "audit", f"select should be exactly 'audit', but got '{select_value}'"

    @pytest.mark.asyncio
    async def test_audit_pattern_matches_all_audit_field_types(self):
        """Test that the regex pattern matches all expected audit field types"""
        pattern = re.compile(r"audit\.(created|updated|completed|processing|quoted)\.(at|by)")

        test_cases = [
            ("audit.created.at", True),
            ("audit.updated.at", True),
            ("audit.completed.at", True),
            ("audit.processing.at", True),
            ("audit.quoted.at", True),
            ("audit.created.by", True),
            ("audit.updated.by", True),
            ("audit.completed.by", True),
            ("audit.processing.by", True),
            ("audit.quoted.by", True),
            ("audit.created.by.id", True),  # Should match the prefix
            ("status", False),
            ("created.at", False),
            ("audit.status", False),
            ("audit.created", False),
        ]

        for field, should_match in test_cases:
            match = pattern.search(field)
            assert (match is not None) == should_match, f"Pattern should {'match' if should_match else 'not match'} '{field}'"


class TestAuditFieldAutoDetectionIntegration:
    """Integration tests for audit field auto-detection with real query patterns"""

    @pytest.fixture
    def api_client(self):
        """Create a mock API client"""
        client = Mock()
        client.get = AsyncMock()
        return client

    @pytest.fixture
    def endpoints_registry(self):
        """Create a mock endpoints registry"""
        return {
            "commerce.orders": {
                "path": "/public/v1/commerce/orders",
                "method": "GET",
            }
        }

    @pytest.fixture
    def mock_api_response(self):
        """Mock API response"""
        return {
            "data": [{"id": "ORD-123", "audit": {"created": {"at": "2026-01-22T10:00:00Z"}}}],
            "$meta": {"pagination": {"total": 1, "limit": 10, "offset": 0}},
        }

    @pytest.mark.asyncio
    async def test_real_world_date_range_query(self, api_client, mock_api_response, endpoints_registry):
        """Test a real-world scenario: filtering orders by date range"""
        api_client.get.return_value = mock_api_response

        rql = 'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),lt(audit.created.at,"2026-01-22T23:59:59Z"))'
        await execute_marketplace_query(
            resource="commerce.orders",
            rql=rql,
            limit=100,
            offset=None,
            page=None,
            select="+id,+product.id,+product.name",
            order="-audit.created.at",
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")

        # Should include audit
        assert "audit" in select_value, "select should include 'audit' for date range queries"
        # Should include original fields
        assert "+id" in select_value
        assert "+product.id" in select_value
        assert "+product.name" in select_value
        # Should have correct order
        assert params.get("order") == "-audit.created.at"

    @pytest.mark.asyncio
    async def test_real_world_recent_orders_query(self, api_client, mock_api_response, endpoints_registry):
        """Test a real-world scenario: getting recent orders sorted by creation date"""
        api_client.get.return_value = mock_api_response

        await execute_marketplace_query(
            resource="commerce.orders",
            rql=None,
            limit=50,
            offset=None,
            page=None,
            select="+id,+status,+product.name",
            order="-audit.created.at",
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        call_args = api_client.get.call_args
        params = call_args.kwargs.get("params", {})
        select_value = params.get("select", "")

        # Should include audit for ordering
        assert "audit" in select_value, "select should include 'audit' when ordering by audit field"
        # Should include original fields
        assert "+id" in select_value
        assert "+status" in select_value
        assert "+product.name" in select_value

    @pytest.mark.asyncio
    async def test_retries_without_audit_on_400_error(self, api_client, mock_api_response, endpoints_registry):
        """Test that if auto-adding audit causes a 400 error, we retry without it"""
        from unittest.mock import AsyncMock

        from httpx import HTTPStatusError, Request, Response

        # First call fails with 400, second succeeds
        error_response = Response(400, json={"errors": {"select": ["Invalid field"]}})
        error_response._request = Request("GET", "https://api.test.com/test")
        http_error = HTTPStatusError("400 Bad Request", request=error_response._request, response=error_response)

        success_response = Mock()
        success_response.json.return_value = mock_api_response
        success_response.raise_for_status = Mock()

        api_client.get = AsyncMock(side_effect=[http_error, success_response])

        await execute_marketplace_query(
            resource="commerce.orders",
            rql='gt(audit.created.at,"2026-01-22T00:00:00Z")',
            limit=10,
            offset=None,
            page=None,
            select="+id,+name",
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            log_fn=lambda x: None,
            analytics_logger=None,
            config=None,
        )

        # Verify API was called twice (first with audit, then retry without)
        assert api_client.get.call_count == 2, "API should be called twice (initial + retry)"

        # First call should have audit
        first_call_params = api_client.get.call_args_list[0].kwargs.get("params", {})
        assert "audit" in first_call_params.get("select", ""), "First call should include 'audit'"

        # Second call (retry) should not have audit, but should have original fields
        second_call_params = api_client.get.call_args_list[1].kwargs.get("params", {})
        assert "audit" not in second_call_params.get("select", ""), "Retry should not include 'audit'"
        assert "+id" in second_call_params.get("select", ""), "Retry should preserve original fields"
        assert "+name" in second_call_params.get("select", ""), "Retry should preserve original fields"
