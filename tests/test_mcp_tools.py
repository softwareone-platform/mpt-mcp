import logging
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import HTTPStatusError, Request, Response

from mpt_mcp.audit_fields import FALLBACK_STATIC_REGEX
from mpt_mcp.mcp_tools import (
    execute_marketplace_query,
    execute_marketplace_resource_info,
    execute_marketplace_resources,
)

PRODUCTS_PAGE_SIZE = 10

QUERY_LIMIT = 50


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


async def test_adds_audit_filtering_by_created_at(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), "select parameter should include 'audit'"


async def test_adds_audit_filtering_by_updated_at(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), "select parameter should include 'audit'"


async def test_adds_audit_filtering_by_completed_at(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), "select parameter should include 'audit'"


async def test_adds_audit_filtering_by_processing_at(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), "select parameter should include 'audit'"


async def test_adds_audit_filtering_by_quoted_at(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), "select parameter should include 'audit'"


async def test_adds_audit_filtering_by_failed_at(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), (
        "select parameter should include 'audit' for audit.failed.at"
    )


async def test_adds_audit_filtering_by_created_by(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), "select parameter should include 'audit'"


async def test_adds_audit_ordering_by_audit_field(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), (
        "select parameter should include 'audit' when ordering by audit field"
    )


async def test_adds_audit_ordering_asc_by_audit_field(
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), (
        "select parameter should include 'audit' when ordering by audit field"
    )


async def test_skips_audit_when_already_in_select(
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    # Count occurrences of 'audit' - should be exactly 1
    audit_count = select_value.count("audit")
    assert audit_count == 1, (
        f"audit should appear exactly once in select, but found {audit_count} times: {select_value}"
    )


async def test_skips_audit_with_plus_prefix(
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    audit_count = select_value.count("audit")
    assert audit_count == 1, (
        f"audit should appear exactly once in select, but found {audit_count} times: {select_value}"
    )


async def test_skips_audit_with_dot_notation(
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    # Should not have standalone 'audit' added, but audit.created.at should be there
    assert "audit.created.at" in select_value, "audit.created.at should be in select"
    # Should not have standalone 'audit' added when audit.field is already present
    select_parts = [part.strip() for part in select_value.split(",")]
    standalone_audit = [part for part in select_parts if part in {"audit", "+audit"}]
    assert len(standalone_audit) == 0, (
        "standalone 'audit' should not be added when audit.field is already present"
    )


async def test_complex_rql_with_audit_fields(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

    rql = (
        'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),'
        'lt(audit.created.at,"2026-01-22T23:59:59Z"))'
    )
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "audit" in query_params.get("select", ""), (
        "select parameter should include 'audit' for complex RQL with audit fields"
    )


async def test_skips_audit_without_audit_fields(
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    assert "audit" not in select_value, (
        "select parameter should NOT include 'audit' when no audit fields are used"
    )


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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    assert "audit" in select_value, "select should include 'audit'"
    assert "id" in select_value, "select should include id (always added by sanitization)"
    assert "name" in select_value, "select should still include original fields"
    assert "status" in select_value, "select should still include original fields"


async def test_creates_audit_select_without_select(
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    assert "audit" in select_value, "select should include 'audit'"
    assert "id" in select_value, "select should include id (always added by sanitization)"


async def test_creates_exact_audit_select(
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

    query_params = api_client.get.call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")
    assert select_value == "id,audit", f"select should be 'id,audit', but got '{select_value}'"


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


async def test_real_world_date_range_query(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

    rql = (
        'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),'
        'lt(audit.created.at,"2026-01-22T23:59:59Z"))'
    )
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")

    # Should include audit
    assert "audit" in select_value, "select should include 'audit' for date range queries"
    # id is always added by sanitization (may appear as 'id' in prefix)
    assert "id" in select_value
    assert "+product.id" in select_value or "product.id" in select_value
    assert "+product.name" in select_value or "product.name" in select_value
    # Should have correct order
    assert query_params.get("order") == "-audit.created.at"


async def test_real_world_recent_orders_query(
    api_client, orders_with_audit_response, endpoints_registry
):
    api_client.get.return_value = orders_with_audit_response

    await execute_marketplace_query(
        resource="commerce.orders",
        rql=None,
        limit=QUERY_LIMIT,
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
    query_params = call_args.kwargs.get("query_params", {})
    select_value = query_params.get("select", "")

    # Should include audit for ordering
    assert "audit" in select_value, "select should include 'audit' when ordering by audit field"
    # id and status are always included by sanitization (canonical prefix)
    assert "id" in select_value
    assert "status" in select_value
    assert "+product.name" in select_value or "product.name" in select_value


async def test_retries_without_audit_on_bad_request(
    api_client, orders_with_audit_response, endpoints_registry
):

    # First call fails with 400, second succeeds
    error_response = Response(
        HTTPStatus.BAD_REQUEST,
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
    first_call_params = api_client.get.call_args_list[0].kwargs.get("query_params", {})
    assert "audit" in first_call_params.get("select", ""), "First call should include 'audit'"

    # Second call (retry) should not have audit, but should have original fields
    second_call_params = api_client.get.call_args_list[1].kwargs.get("query_params", {})
    assert "audit" not in second_call_params.get("select", ""), "Retry should not include 'audit'"
    assert "+id" in second_call_params.get("select", ""), "Retry should preserve original fields"
    assert "+name" in second_call_params.get("select", ""), "Retry should preserve original fields"


@pytest.fixture
def products_page_response():
    return {
        "data": [
            {"id": f"prod-{index}", "name": f"Product {index}"}
            for index in range(1, PRODUCTS_PAGE_SIZE + 1)
        ],
        "$meta": {"pagination": {"total": 100, "limit": 10, "offset": 0}},
    }


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

    # Check that limit=10 was passed in query_params
    query_params = call_args.kwargs.get("query_params", {})
    assert "limit" in query_params, "Limit parameter should be present"
    assert query_params["limit"] == 10, f"Expected limit=10, got limit={query_params.get('limit')}"

    # Verify result
    assert "data" in result
    assert "$meta" in result


async def test_respects_explicit_limit(api_client, products_page_response, endpoints_registry):
    api_client.get.return_value = products_page_response

    # Test with limit=50
    result = await execute_marketplace_query(
        resource="catalog.products",
        rql="",
        limit=QUERY_LIMIT,  # Explicit limit
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
    query_params = call_args.kwargs.get("query_params", {})
    assert query_params["limit"] == QUERY_LIMIT

    # Verify result
    assert "data" in result


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
    query_params = call_args.kwargs.get("query_params", {})
    assert query_params["limit"] == 0, f"Expected limit=0, got limit={query_params.get('limit')}"
    assert "data" in result


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
    query_params = call_args.kwargs.get("query_params", {})
    assert query_params["rql"] == "eq(status,Published)", "RQL should be preserved"
    assert query_params["limit"] == 10, "Default limit should be applied"
    assert "data" in result


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
    query_params = call_args.kwargs.get("query_params", {})
    assert {"id", "name"} <= set(query_params["select"].split(","))
    assert query_params["order"] == "-created", "Order should be preserved"
    assert query_params["limit"] == 10, "Default limit should be applied"
    assert "data" in result


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


async def test_catalog_products_default_select(
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

    query_params = api_client.get.call_args.kwargs.get("query_params", {})
    sel = query_params.get("select") or ""
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
    query_params = call_args.kwargs.get("query_params", {})
    assert "select" in query_params
    # orderNumber must be dropped; id must be present
    assert "orderNumber" not in query_params["select"]
    assert "id" in query_params["select"]
    assert "audit" in query_params["select"]
    assert "status" in query_params["select"]


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

    query_params = api_client.get.call_args.kwargs.get("query_params", {})
    assert "select" in query_params
    assert "id" in query_params["select"]
    assert "audit" in query_params["select"]
    assert "status" in query_params["select"]


def test_resource_info_notes_omitted_fields(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="commerce.orders",
        endpoints_registry=endpoints_registry,
    )

    # Verify omitted_fields_note is present
    assert "omitted_fields_note" in result
    assert "omitted" in result["omitted_fields_note"].lower()
    assert "$meta.omitted" in result["omitted_fields_note"]
    assert "select=+field" in result["omitted_fields_note"]


def test_resource_info_select_documents_omitted(endpoints_registry):
    result = execute_marketplace_resource_info(
        resource="commerce.orders",
        endpoints_registry=endpoints_registry,
    )

    # Verify select parameter documentation mentions omitted fields
    assert "common_parameters" in result
    select_doc = result["common_parameters"]["select"]
    assert "omitted" in select_doc.lower() or "$meta.omitted" in select_doc
    assert "select=+field" in select_doc or "+field" in select_doc


def test_resources_tips_mention_omitted_fields():
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


def test_resource_info_handles_unknown_resource(endpoints_registry):
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
        return api_client.get.call_args.kwargs["query_params"].get("select")

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
