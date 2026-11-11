import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from mpt_mcp.auth.call_context import CallContext
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.tools.query.params import DEFAULT_LIMIT
from mpt_mcp.tools.query.tool import log_query_result, marketplace_query, query_tools


@pytest.fixture
def api_client():
    return Mock(spec=APIClient, get=AsyncMock())


@pytest.fixture
def query_server():
    mcp = FastMCP("test")
    mcp.add_provider(query_tools)
    return mcp


async def test_query_sends_resource_query(api_client, spec_factory):
    api_client.get.return_value = {"data": [], "$meta": {"pagination": {"total": 0}}}
    registry = {"commerce.orders.lines": {"path": "/public/v1/commerce/orders/{orderId}/lines"}}

    await marketplace_query(  # act
        "commerce.orders.lines",
        rql="eq(status,Active)",
        path_params={"orderId": "ORD-1234-5678"},
        api_client=api_client,
        spec=spec_factory(registry=registry),
        analytics_logger=None,
    )

    assert api_client.get.call_args.args == ("/public/v1/commerce/orders/ORD-1234-5678/lines",)
    assert api_client.get.call_args.kwargs["query_params"] == {
        "rql": "eq(status,Active)",
        "limit": DEFAULT_LIMIT,
    }


async def test_query_unknown_resource_sends_nothing(api_client, spec_factory):
    spec = spec_factory()

    with pytest.raises(ToolError, match="Unknown resource"):
        await marketplace_query(
            "invalid.resource", api_client=api_client, spec=spec, analytics_logger=None
        )

    api_client.get.assert_not_called()


@pytest.mark.parametrize(
    ("page_args", "expected_error"),
    [
        ({"limit": 101}, "less than or equal to 100"),
        ({"limit": -1}, "greater than or equal to 0"),
        ({"offset": -1}, "greater than or equal to 0"),
    ],
)
async def test_query_rejects_page_out_of_range(query_server, page_args, expected_error):
    with patch.object(CallContext, "create_api_client", new_callable=AsyncMock) as create_client:
        async with Client(query_server) as client:
            result = await client.call_tool(
                "marketplace_query",
                {"resource": "commerce.orders", **page_args},
                raise_on_error=False,
            )

    assert result.is_error
    assert expected_error in result.content[0].text
    create_client.assert_not_awaited()


async def test_query_schema_hides_dependencies(query_server):
    async with Client(query_server) as client:
        tools = await client.list_tools()

    properties = tools[0].input_schema["properties"]
    assert "api_client" not in properties
    assert "spec" not in properties
    assert "analytics_logger" not in properties
    assert properties["limit"] | {"description": None} == {
        "default": DEFAULT_LIMIT,
        "description": None,
        "maximum": 100,
        "minimum": 0,
        "type": "integer",
    }


async def test_query_wraps_plain_values(api_client, spec_factory):
    registry = {"commerce.orders.render": {"path": "/public/v1/commerce/orders/render"}}
    api_client.get.return_value = "<h1>Order</h1>"

    result = (
        await marketplace_query(
            "commerce.orders.render",
            api_client=api_client,
            spec=spec_factory(registry=registry),
            analytics_logger=None,
        )
    ).model_dump()

    assert result == {"result": "<h1>Order</h1>"}


async def test_query_next_offset_continues_cut_page(api_client, spec_factory):
    api_client.get.return_value = {
        "$meta": {"pagination": {"offset": 0, "limit": 100, "total": 500}},
        "data": [{"id": f"ORD-{index}", "notes": "x" * 1000} for index in range(100)],
    }

    result = (
        await marketplace_query(
            "commerce.orders",
            limit=100,
            api_client=api_client,
            spec=spec_factory(),
            analytics_logger=None,
        )
    ).model_dump(by_alias=True)

    pagination = result["$meta"]["pagination"]
    assert len(result["data"]) < 100
    assert pagination["has_more"] is True
    assert pagination["next_offset"] == len(result["data"])
    assert pagination["returned"] == pagination["next_offset"]
    assert result["$meta"]["truncated"]["suggested_limit"] == len(result["data"])


@pytest.mark.parametrize(
    ("result", "expected_log"),
    [
        ({"data": [{"id": "ORD-1"}], "$meta": {}}, "Returning: data len=1, $meta=no"),
        ({"id": "ORD-1", "$meta": {"omitted": ["lines"]}}, "Returning: single item, $meta=yes"),
        (3, "Returning: int value"),
    ],
)
def test_log_query_result(caplog, result, expected_log):
    caplog.set_level(logging.INFO)

    log_query_result(result)  # act

    assert expected_log in caplog.text
