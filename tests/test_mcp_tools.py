import logging
import re
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import HTTPStatusError, Request, Response

from mpt_mcp.mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_resource_info,
    execute_marketplace_resources,
)


@pytest.fixture
def api_client():
    client = Mock()
    client.get = AsyncMock()
    return client


@pytest.fixture
def endpoints_registry():
    return {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "method": "GET",
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "method": "GET",
            "summary": "List orders",
            "description": "Get a list of orders",
            "parameters": [],
        },
    }


@pytest.fixture
def orders_with_audit_response():
    return {
        "data": [
            {
                "id": "ORD-123",
                "status": "Completed",
                "audit": {
                    "created": {
                        "at": "2026-01-22T10:00:00Z",
                        "by": {"id": "USR-1", "name": "User 1"},
                    },
                    "updated": {
                        "at": "2026-01-22T11:00:00Z",
                        "by": {"id": "USR-2", "name": "User 2"},
                    },
                },
            }
        ],
        "$meta": {"pagination": {"total": 1, "limit": 10, "offset": 0}},
    }


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_created_at(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    # Verify API was called with select=audit
    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), "select parameter should include 'audit'"


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_updated_at(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), "select parameter should include 'audit'"


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_completed_at(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

    rql = 'ge(audit.completed.at,"2026-01-22T00:00:00Z")'
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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), "select parameter should include 'audit'"


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_processing_at(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), "select parameter should include 'audit'"


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_quoted_at(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), "select parameter should include 'audit'"


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_failed_at(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

    rql = 'ge(audit.failed.at,"2026-01-22T00:00:00Z")'
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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), (
        "select parameter should include 'audit' for audit.failed.at"
    )


@pytest.mark.asyncio
async def test_auto_adds_audit_when_filtering_by_created_by(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), "select parameter should include 'audit'"


@pytest.mark.asyncio
async def test_auto_adds_audit_when_ordering_by_audit_field(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), (
        "select parameter should include 'audit' when ordering by audit field"
    )


@pytest.mark.asyncio
async def test_auto_adds_audit_when_ordering_ascending_by_audit_field(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), (
        "select parameter should include 'audit' when ordering by audit field"
    )


@pytest.mark.asyncio
async def test_does_not_add_audit_when_already_in_select(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")
    # Count occurrences of 'audit' - should be exactly 1
    audit_count = select_value.count("audit")
    assert audit_count == 1, (
        f"audit should appear exactly once in select, but found {audit_count} times: {select_value}"
    )


@pytest.mark.asyncio
async def test_does_not_add_audit_when_using_plus_prefix(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")
    audit_count = select_value.count("audit")
    assert audit_count == 1, (
        f"audit should appear exactly once in select, but found {audit_count} times: {select_value}"
    )


@pytest.mark.asyncio
async def test_does_not_add_audit_when_using_audit_dot_notation(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
    assert len(standalone_audit) == 0, (
        "standalone 'audit' should not be added when audit.field is already present"
    )


@pytest.mark.asyncio
async def test_complex_rql_with_audit_fields(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert "audit" in params.get("select", ""), (
        "select parameter should include 'audit' for complex RQL with audit fields"
    )


@pytest.mark.asyncio
async def test_does_not_add_audit_when_no_audit_fields_used(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")
    assert "audit" not in select_value, (
        "select parameter should NOT include 'audit' when no audit fields are used"
    )


@pytest.mark.asyncio
async def test_appends_audit_to_existing_select(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")
    assert "audit" in select_value, "select should include 'audit'"
    assert "id" in select_value, "select should include id (always added by sanitization)"
    assert "name" in select_value, "select should still include original fields"
    assert "status" in select_value, "select should still include original fields"


@pytest.mark.asyncio
async def test_creates_select_with_audit_when_no_select_provided(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")
    assert "audit" in select_value, "select should include 'audit'"
    assert "id" in select_value, "select should include id (always added by sanitization)"


@pytest.mark.asyncio
async def test_creates_select_with_audit_when_no_select_provided_exact(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    params = api_client.get.call_args.kwargs.get("params", {})
    select_value = params.get("select", "")
    assert select_value == "id,audit", f"select should be 'id,audit', but got '{select_value}'"


@pytest.mark.asyncio
async def test_audit_pattern_matches_all_audit_field_types():
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
        assert (match is not None) == should_match, (
            f"Pattern should {'match' if should_match else 'not match'} '{field}'"
        )


@pytest.mark.asyncio
async def test_real_world_date_range_query(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")

    # Should include audit
    assert "audit" in select_value, "select should include 'audit' for date range queries"
    # id is always added by sanitization (may appear as 'id' in prefix)
    assert "id" in select_value
    assert "+product.id" in select_value or "product.id" in select_value
    assert "+product.name" in select_value or "product.name" in select_value
    # Should have correct order
    assert params.get("order") == "-audit.created.at"


@pytest.mark.asyncio
async def test_real_world_recent_orders_query(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

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
        analytics_logger=None,
        config=None,
    )

    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    select_value = params.get("select", "")

    # Should include audit for ordering
    assert "audit" in select_value, "select should include 'audit' when ordering by audit field"
    # id and status are always included by sanitization (canonical prefix)
    assert "id" in select_value
    assert "status" in select_value
    assert "+product.name" in select_value or "product.name" in select_value


@pytest.mark.asyncio
async def test_retries_without_audit_on_400_error(
    api_client, orders_with_audit_response, endpoints_registry
):

    # First call fails with 400, second succeeds
    error_response = Response(
        400,
        json={"errors": {"select": ["Invalid field"]}},
        request=Request("GET", "https://api.test.com/test"),
    )
    http_error = HTTPStatusError(
        "400 Bad Request", request=error_response.request, response=error_response
    )

    success_response = Mock()
    success_response.json.return_value = orders_with_audit_response
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


@pytest.fixture
def products_page_response():
    return {
        "data": [{"id": f"prod-{i}", "name": f"Product {i}"} for i in range(1, 11)],
        "$meta": {"pagination": {"total": 100, "limit": 10, "offset": 0}},
    }


@pytest.mark.asyncio
async def test_applies_default_limit_when_none(
    api_client, products_page_response, endpoints_registry
):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="",
        limit=None,  # No limit specified
        offset=None,
        page=None,
        select=None,
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    # Verify API was called with limit=10
    call_args = api_client.get.call_args
    assert call_args is not None, "API client should have been called"

    # Check that limit=10 was passed in params
    params = call_args.kwargs.get("params", {})
    assert "limit" in params, "Limit parameter should be present"
    assert params["limit"] == 10, f"Expected limit=10, got limit={params.get('limit')}"

    # Verify result
    assert "data" in result
    assert "$meta" in result


@pytest.mark.asyncio
async def test_respects_explicit_limit(api_client, products_page_response, endpoints_registry):
    api_client.get.return_value = products_page_response

    # Test with limit=50
    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="",
        limit=50,  # Explicit limit
        offset=None,
        page=None,
        select=None,
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    # Verify API was called with limit=50 (not default 10)
    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params["limit"] == 50, f"Expected limit=50, got limit={params.get('limit')}"

    # Verify result
    assert "data" in result


@pytest.mark.asyncio
async def test_respects_limit_zero(api_client, products_page_response, endpoints_registry):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="",
        limit=0,  # Explicit limit=0
        offset=None,
        page=None,
        select=None,
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    # Verify API was called with limit=0 (not default 10)
    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params["limit"] == 0, f"Expected limit=0, got limit={params.get('limit')}"
    assert "data" in result


@pytest.mark.asyncio
async def test_default_limit_with_rql(api_client, products_page_response, endpoints_registry):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="eq(status,Published)",  # RQL query
        limit=None,  # No limit specified
        offset=None,
        page=None,
        select=None,
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    # Verify API was called with both RQL and limit=10
    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert params["rql"] == "eq(status,Published)", "RQL should be preserved"
    assert params["limit"] == 10, "Default limit should be applied"
    assert "data" in result


@pytest.mark.asyncio
async def test_default_limit_with_other_params(
    api_client, products_page_response, endpoints_registry
):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="",
        limit=None,  # No limit specified
        offset=None,
        page=None,
        select="+id,+name",  # Select parameter
        order="-created",  # Order parameter
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    # Verify API was called with all parameters including default limit
    call_args = api_client.get.call_args
    params = call_args.kwargs.get("params", {})
    assert {"id", "name"} <= set(params["select"].split(","))
    assert params["order"] == "-created", "Order should be preserved"
    assert params["limit"] == 10, "Default limit should be applied"
    assert "data" in result


@pytest.mark.asyncio
async def test_default_limit_logs_message(
    api_client, products_page_response, endpoints_registry, caplog
):
    api_client.get.return_value = products_page_response

    with caplog.at_level(logging.INFO, logger="mpt_mcp.mcp_tools"):
        await execute_marketplace_query(
            resource="catalog.products",
            rql="",
            limit=None,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )

    assert "default limit=10" in caplog.text.lower()


@pytest.mark.asyncio
async def test_catalog_products_default_select_when_omit(
    api_client, products_page_response, endpoints_registry
):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="",
        limit=10,
        offset=None,
        page=None,
        select=None,
        order=None,
        path_params=None,
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    params = api_client.get.call_args.kwargs.get("params", {})
    sel = params.get("select") or ""
    assert {"id", "name", "+shortDescription"} <= set(sel.split(","))
    assert "data" in result


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
def orders_response():
    return {
        "data": [{"id": "ord-1", "status": "Created", "audit": {}}],
        "$meta": {"pagination": {"total": 1, "limit": 100, "offset": 0}},
    }


@pytest.mark.asyncio
async def test_sanitizes_select_drops_invalid_adds_id(
    api_client, endpoints_registry, openapi_spec, orders_response
):
    api_client.get.return_value = orders_response

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
async def test_select_without_openapi_spec_adds_id(api_client, endpoints_registry, orders_response):
    api_client.get.return_value = orders_response

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


@pytest.mark.asyncio
async def test_marketplace_resource_info_includes_omitted_fields_note(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="commerce.orders",
        endpoints_registry=endpoints_registry,
    )

    # Verify omitted_fields_note is present
    assert "omitted_fields_note" in result
    assert "omitted" in result["omitted_fields_note"].lower()
    assert "$meta.omitted" in result["omitted_fields_note"]
    assert "select=+field" in result["omitted_fields_note"]


@pytest.mark.asyncio
async def test_marketplace_resource_info_select_param_documents_omitted_fields(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="commerce.orders",
        endpoints_registry=endpoints_registry,
    )

    # Verify select parameter documentation mentions omitted fields
    assert "common_parameters" in result
    select_doc = result["common_parameters"]["select"]
    assert "omitted" in select_doc.lower() or "$meta.omitted" in select_doc
    assert "select=+field" in select_doc or "+field" in select_doc


@pytest.mark.asyncio
async def test_marketplace_resources_tips_mention_omitted_fields():
    mock_registry = {
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "method": "GET",
            "summary": "List orders",
            "parameters": [],
        }
    }

    result = execute_marketplace_resources(
        endpoints_registry=mock_registry,
        api_base_url="https://api.test.com",
        user_id="test-user",
    )

    # Verify tips include information about omitted fields
    assert "tips" in result
    assert "field_selection" in result["tips"]
    field_selection_tip = result["tips"]["field_selection"]
    assert "omitted" in field_selection_tip.lower() or "$meta.omitted" in field_selection_tip
    assert "select=+field" in field_selection_tip or "+field" in field_selection_tip


@pytest.mark.asyncio
async def test_marketplace_resource_info_handles_unknown_resource(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="unknown.resource",
        endpoints_registry=endpoints_registry,
    )

    # Should return error, not crash
    assert "error" in result
    assert "Unknown resource" in result["error"]


@pytest.fixture
def openapi_spec_with_fields():
    def _openapi_spec_with_fields(fields):
        item_schema = {
            "type": "object",
            "properties": {field: {"type": "string"} for field in fields},
        }
        list_schema = {
            "type": "object",
            "properties": {"data": {"type": "array", "items": item_schema}},
        }
        response = {"200": {"content": {"application/json": {"schema": list_schema}}}}
        return {"paths": {"/public/v1/commerce/orders": {"get": {"responses": response}}}}

    return _openapi_spec_with_fields


@pytest.fixture
def sent_select(api_client, endpoints_registry, orders_response, openapi_spec_with_fields):
    async def _sent_select(select, fields):
        api_client.get.return_value = orders_response
        await execute_marketplace_query(
            resource="commerce.orders",
            rql="",
            limit=10,
            offset=None,
            page=None,
            select=select,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            openapi_spec=openapi_spec_with_fields(fields) if fields is not None else None,
        )
        return api_client.get.call_args.kwargs["params"].get("select")

    return _sent_select


@pytest.mark.parametrize(
    ("select", "fields", "expected"),
    [
        (None, None, None),
        ("", ["id", "audit", "status"], None),
        ("  ", ["id", "audit", "status"], "  "),
        ("audit,status", None, "id,status,audit"),
        ("audit,status", ["id", "audit", "status"], "id,status,audit"),
        ("id,audit,status", ["id", "audit", "status"], "id,status,audit"),
        ("audit,status,orderNumber", ["id", "audit", "status"], "id,status,audit"),
        ("+audit,+status", ["id", "audit", "status"], "id,status,+audit"),
        ("audit.created.at,status", ["id", "audit", "status"], "id,status,audit.created.at"),
        ("audit", ["id", "status", "name", "audit"], "id,status,name,audit"),
        ("id,audit", ["id", "status", "name", "audit"], "id,status,name,audit"),
    ],
)
async def test_query_sanitizes_select_against_schema(sent_select, select, fields, expected):
    result = await sent_select(select, fields)

    assert result == expected


@pytest.fixture
def query_path(api_client):
    async def _query_path(path_template, path_params):
        api_client.get.return_value = {"data": [], "$meta": {"pagination": {"total": 0}}}
        return await execute_marketplace_query(
            resource="test.resource",
            rql="",
            limit=10,
            offset=None,
            page=None,
            select=None,
            order=None,
            path_params=path_params,
            api_client=api_client,
            endpoints_registry={"test.resource": {"path": path_template}},
        )

    return _query_path


@pytest.mark.parametrize(
    ("path_template", "path_params", "expected_path"),
    [
        (
            "/public/v1/catalog/products/{id}",
            {"id": "PRD-1234-5678"},
            "/public/v1/catalog/products/PRD-1234-5678",
        ),
        (
            "/public/v1/commerce/orders/{orderId}/lines/{lineId}",
            {"orderId": "ORD-1234-5678", "lineId": "LIN-9876-5432"},
            "/public/v1/commerce/orders/ORD-1234-5678/lines/LIN-9876-5432",
        ),
        ("/public/v1/catalog/items", None, "/public/v1/catalog/items"),
        ("/public/v1/system/tasks/{id}", {"id": 12345}, "/public/v1/system/tasks/12345"),
    ],
)
async def test_query_replaces_path_params(
    api_client, query_path, path_template, path_params, expected_path
):
    await query_path(path_template, path_params)  # act

    assert api_client.get.call_args.args[0] == expected_path


async def test_query_reports_missing_path_params(api_client, query_path):
    result = await query_path(
        "/public/v1/commerce/orders/{orderId}/lines/{lineId}", {"orderId": "ORD-1234-5678"}
    )

    assert result["error"] == "This resource requires path parameters: lineId"
    assert "'lineId': 'LIN-1234-5678'" in result["hint"]
    api_client.get.assert_not_called()
