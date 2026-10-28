#!/usr/bin/env python3

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from mpt_mcp.mcp_tools import execute_marketplace_query


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
        }
    }


@pytest.fixture
def mock_api_response():
    return {
        "data": [{"id": f"prod-{i}", "name": f"Product {i}"} for i in range(1, 11)],
        "$meta": {"pagination": {"total": 100, "limit": 10, "offset": 0}},
    }


@pytest.mark.asyncio
async def test_applies_default_limit_when_none(api_client, mock_api_response, endpoints_registry):
    api_client.get.return_value = mock_api_response

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
async def test_respects_explicit_limit(api_client, mock_api_response, endpoints_registry):
    api_client.get.return_value = mock_api_response

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
async def test_respects_limit_zero(api_client, mock_api_response, endpoints_registry):
    api_client.get.return_value = mock_api_response

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
async def test_default_limit_with_rql(api_client, mock_api_response, endpoints_registry):
    api_client.get.return_value = mock_api_response

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
async def test_default_limit_with_other_params(api_client, mock_api_response, endpoints_registry):
    api_client.get.return_value = mock_api_response

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
    assert "id" in params["select"] and "name" in params["select"], "Select should include id and name (sanitization may reorder to canonical id,name,...)"
    assert params["order"] == "-created", "Order should be preserved"
    assert params["limit"] == 10, "Default limit should be applied"
    assert "data" in result


@pytest.mark.asyncio
async def test_default_limit_logs_message(api_client, mock_api_response, endpoints_registry, caplog):
    api_client.get.return_value = mock_api_response

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
async def test_catalog_products_default_select_when_omit(api_client, mock_api_response, endpoints_registry):
    api_client.get.return_value = mock_api_response

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
    assert "id" in sel and "name" in sel and "shortDescription" in sel, f"Expected default select for catalog.products to include id, name, shortDescription, got: {sel}"
    assert "data" in result
