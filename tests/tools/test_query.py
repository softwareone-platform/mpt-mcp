import json
import logging
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.auth.call_context import CallContext
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.tools.query import execute_marketplace_query, marketplace_query, suggest_resources
from mpt_mcp.tools.results import AUTH_HEADER_HINT

PRODUCTS_PAGE_SIZE = 10
QUERY_LIMIT = 50
AUDIT_RQL = 'gt(audit.created.at,"2026-01-22T00:00:00Z")'
DATE_RANGE_RQL = (
    'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),lt(audit.created.at,"2026-01-22T23:59:59Z"))'
)


@pytest.fixture
def query_defaults():
    return {
        "resource": "commerce.orders",
        "rql": "",
        "limit": 10,
        "offset": None,
        "select": None,
        "order": None,
        "path_params": None,
    }


@pytest.fixture
def api_client():
    return Mock(spec=APIClient, get=AsyncMock())


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


@pytest.fixture
def products_page_response():
    return {
        "data": [
            {"id": f"prod-{index}", "name": f"Product {index}"}
            for index in range(1, PRODUCTS_PAGE_SIZE + 1)
        ],
        "$meta": {"pagination": {"total": 100, "limit": 10, "offset": 0}},
    }


@pytest.fixture
def send_query(api_client, endpoints_registry, orders_with_audit_response, query_defaults):
    async def factory(response=None, **query_args):
        api_client.get.return_value = response or orders_with_audit_response
        await execute_marketplace_query(
            **{**query_defaults, **query_args},
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )
        return api_client.get.call_args.kwargs["query_params"]

    return factory


@pytest.fixture
def send_select(send_query):
    async def factory(**query_args):
        query_params = await send_query(**query_args)
        select = query_params.get("select", "")
        return [part.lstrip("+") for part in select.split(",")] if select else []

    return factory


@pytest.fixture
def orders_response():
    return {
        "data": [{"id": "ord-1", "status": "Created", "audit": {}}],
        "$meta": {"pagination": {"total": 1, "limit": 100, "offset": 0}},
    }


@pytest.fixture
def sent_select(api_client, endpoints_registry, orders_response, openapi_spec_factory):
    async def factory(select, fields):
        api_client.get.return_value = orders_response
        await execute_marketplace_query(
            resource="commerce.orders",
            rql="",
            limit=10,
            offset=None,
            select=select,
            order=None,
            path_params=None,
            api_client=api_client,
            endpoints_registry=endpoints_registry,
            openapi_spec=None if fields is None else openapi_spec_factory(fields),
        )
        return api_client.get.call_args.kwargs["query_params"].get("select")

    return factory


@pytest.fixture
def query_path(api_client):
    async def factory(path_template, path_params):
        api_client.get.return_value = {"data": [], "$meta": {"pagination": {"total": 0}}}
        return await execute_marketplace_query(
            resource="test.resource",
            rql="",
            limit=10,
            offset=None,
            select=None,
            order=None,
            path_params=path_params,
            api_client=api_client,
            endpoints_registry={"test.resource": {"path": path_template}},
        )

    return factory


@pytest.mark.parametrize(
    ("rql", "order"),
    [
        ('gt(audit.created.at,"2026-01-22T00:00:00Z")', None),
        ('lt(audit.updated.at,"2026-01-22T23:59:59Z")', None),
        ('ge(audit.completed.at,"2026-01-22T00:00:00Z")', None),
        ('eq(audit.processing.at,"2026-01-22T10:00:00Z")', None),
        ('lte(audit.quoted.at,"2026-01-22T23:59:59Z")', None),
        ('ge(audit.failed.at,"2026-01-22T00:00:00Z")', None),
        ('eq(audit.created.by.id,"USR-123")', None),
        ("", "-audit.created.at"),
        ("", "+audit.updated.at"),
        (DATE_RANGE_RQL, "-audit.created.at"),
    ],
)
async def test_adds_audit_to_select_for_audit_fields(send_select, rql, order):
    result = await send_select(rql=rql, order=order)

    assert any(part.startswith("audit.") for part in result)


@pytest.mark.parametrize("select", ["audit,+id,+name", "+audit,+id,+name"])
async def test_keeps_single_audit_in_select(send_select, select):
    result = await send_select(rql=AUDIT_RQL, select=select)

    assert result.count("audit") == 1


async def test_skips_audit_with_dot_notation(send_select):
    result = await send_select(rql=AUDIT_RQL, select="+audit.created.at,+id,+name")

    assert "audit.created.at" in result
    assert "audit" not in result


async def test_skips_audit_without_audit_fields(send_select):
    result = await send_select(rql='eq(status,"Completed")', order="-status")

    assert "audit" not in result


async def test_appends_audit_to_existing_select(send_select):
    result = await send_select(rql=AUDIT_RQL, select="+id,+name,+status")

    assert {"audit.created.at", "id", "name", "status"} <= set(result)


async def test_creates_audit_select_without_select(send_query):
    result = await send_query(rql=AUDIT_RQL)

    assert result["select"] == "id,+audit.created.at"


async def test_adds_used_audit_fields_with_exclude_all(send_select):
    result = await send_select(
        rql=AUDIT_RQL, select="-*,+id,+status", order="-audit.updated.at,-audit.created.at"
    )

    assert result == ["-*", "id", "status", "audit.created.at", "audit.updated.at"]


async def test_adds_used_audit_fields_to_default(send_select):
    result = await send_select(rql=AUDIT_RQL, select="+id,+status")

    assert result == ["id", "status", "audit.created.at"]


async def test_real_world_date_range_query(send_query):
    result = await send_query(
        rql=DATE_RANGE_RQL,
        limit=100,
        select="+id,+product.id,+product.name",
        order="-audit.created.at",
    )

    select_fields = {part.lstrip("+") for part in result["select"].split(",")}
    assert {"audit.created.at", "id", "product.id", "product.name"} <= select_fields
    assert result["order"] == "-audit.created.at"


async def test_real_world_recent_orders_query(send_select):
    result = await send_select(
        limit=QUERY_LIMIT, select="+id,+status,+product.name", order="-audit.created.at"
    )

    assert {"audit.created.at", "id", "status", "product.name"} <= set(result)


async def test_retries_without_audit_on_bad_request(
    api_client, orders_with_audit_response, endpoints_registry, query_defaults
):
    error_response = httpx.Response(
        HTTPStatus.BAD_REQUEST,
        json={"errors": {"select": ["Invalid field"]}},
        request=httpx.Request("GET", "https://api.test.com/test"),
    )
    http_error = httpx.HTTPStatusError(
        "400 Bad Request", request=error_response.request, response=error_response
    )
    api_client.get = AsyncMock(side_effect=[http_error, orders_with_audit_response])

    await execute_marketplace_query(  # act
        **{**query_defaults, "rql": AUDIT_RQL, "select": "+id,+name"},
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    sent_params = [call.kwargs["query_params"] for call in api_client.get.call_args_list]
    sent_selects = [query_params["select"] for query_params in sent_params]
    assert "audit" in sent_selects[0]
    assert "audit" not in sent_selects[1]
    assert {"+id", "+name"} <= set(sent_selects[1].split(","))


async def test_returns_api_response(
    api_client, products_page_response, endpoints_registry, query_defaults
):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        **{**query_defaults, "resource": "catalog.products"},
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    assert result["data"] == products_page_response["data"]


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (None, 10),
        (QUERY_LIMIT, QUERY_LIMIT),
        (0, 0),
    ],
)
async def test_sends_limit(send_query, products_page_response, limit, expected):
    result = await send_query(
        response=products_page_response, resource="catalog.products", limit=limit
    )

    assert result["limit"] == expected


async def test_default_limit_with_rql(send_query, products_page_response):
    result = await send_query(
        response=products_page_response,
        resource="catalog.products",
        rql="eq(status,Published)",
        limit=None,
    )

    assert (result["rql"], result["limit"]) == ("eq(status,Published)", 10)


async def test_default_limit_with_other_params(send_query, products_page_response):
    result = await send_query(
        response=products_page_response,
        resource="catalog.products",
        limit=None,
        select="+id,+name",
        order="-created",
    )

    assert {"id", "name"} <= set(result["select"].split(","))
    assert (result["order"], result["limit"]) == ("-created", 10)


async def test_default_limit_logs_message(send_query, products_page_response, caplog):
    with caplog.at_level(logging.INFO, logger="mpt_mcp.tools.query"):
        await send_query(  # act
            response=products_page_response, resource="catalog.products", limit=None
        )

    assert "default limit=10" in caplog.text.lower()


async def test_catalog_products_default_select(send_query, products_page_response):
    result = await send_query(response=products_page_response, resource="catalog.products")

    assert result["select"] == "-*,+id,+name,+shortDescription"


async def test_sanitizes_select_drops_invalid_adds_id(send_select, openapi_spec, orders_response):
    result = await send_select(
        response=orders_response, select="audit,status,orderNumber", openapi_spec=openapi_spec
    )

    assert {"id", "audit", "status"} <= set(result)
    assert "orderNumber" not in result


async def test_select_without_openapi_spec_adds_id(send_select, orders_response):
    result = await send_select(response=orders_response, select="audit,status")

    assert {"id", "audit", "status"} <= set(result)


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


@pytest.mark.parametrize(
    ("path_template", "expected"),
    [
        ("/public/v1/commerce/orders/{id}", {}),
        ("/public/v1/commerce/orders/{orderId}/lines", {"limit": 10}),
    ],
)
async def test_query_limits_only_collections(api_client, query_path, path_template, expected):
    await query_path(path_template, {"id": "ORD-1234-5678", "orderId": "ORD-1234-5678"})  # act

    query_params = api_client.get.call_args.kwargs["query_params"]
    assert {
        key: query_params[key] for key in ("limit", "offset") if key in query_params
    } == expected


async def test_query_reports_missing_path_params(api_client, query_path):
    with pytest.raises(ToolError) as error:
        await query_path(
            "/public/v1/commerce/orders/{orderId}/lines/{lineId}", {"orderId": "ORD-1234-5678"}
        )

    message, details = str(error.value).split("\n", 1)
    assert message == "This resource requires path parameters: lineId"
    assert "'lineId': 'LIN-1234-5678'" in json.loads(details)["hint"]
    api_client.get.assert_not_called()


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("catalog.product", ["catalog.products"]),
        ("catalog.prodcts", ["catalog.products"]),
        ("Commerce.Orders", ["commerce.orders"]),
        ("billing.unknown", []),
    ],
)
def test_suggest_resources(resource, expected):
    resources = ["catalog.products", "commerce.orders", "accounts.buyers"]

    result = suggest_resources(resource, resources)

    assert result == expected


def test_suggest_resources_containing_first():
    resources = [f"catalog.products.item{index}" for index in range(6)] + ["catalog.producs"]

    result = suggest_resources("catalog.products", resources)

    assert result == [f"catalog.products.item{index}" for index in range(5)]


def test_suggest_resources_closest_first():
    resources = [f"public-catalog.product-profiles.item{index}" for index in range(6)]
    resources.append("catalog.products")

    result = suggest_resources("catalog.product", resources)

    assert result[0] == "catalog.products"


async def test_query_without_credentials_fails(call_context, registry_loader):
    with (
        patch.object(
            CallContext,
            "create_api_client",
            new_callable=AsyncMock,
            side_effect=ValueError("Missing X-MPT-Authorization header"),
        ),
        pytest.raises(ToolError, match="Missing X-MPT-Authorization header") as error,
    ):
        await marketplace_query("catalog.products", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details == {"hint": AUTH_HEADER_HINT}


async def test_query_wraps_plain_values(call_context, registry_loader, patched_api_client):
    registry_loader.return_value = {
        "commerce.orders.render": {"path": "/public/v1/commerce/orders/render", "parameters": []}
    }
    patched_api_client.get = AsyncMock(return_value="<h1>Order</h1>")

    result = (
        await marketplace_query("commerce.orders.render", call_context=call_context)
    ).model_dump()

    assert result == {"result": "<h1>Order</h1>"}


async def test_query_next_offset_continues_cut_page(
    call_context, registry_loader, patched_api_client
):
    registry_loader.return_value = {
        "commerce.orders": {"path": "/public/v1/commerce/orders", "parameters": []}
    }
    patched_api_client.get = AsyncMock(
        return_value={
            "$meta": {"pagination": {"offset": 0, "limit": 100, "total": 500}},
            "data": [{"id": f"ORD-{index}", "notes": "x" * 1000} for index in range(100)],
        }
    )

    result = (
        await marketplace_query("commerce.orders", limit=100, call_context=call_context)
    ).model_dump(by_alias=True)

    pagination = result["$meta"]["pagination"]
    assert len(result["data"]) < 100
    assert pagination["has_more"] is True
    assert pagination["next_offset"] == len(result["data"])
    assert pagination["returned"] == pagination["next_offset"]
    assert result["$meta"]["truncated"]["suggested_limit"] == len(result["data"])


async def test_unknown_resource_suggests_similar(call_context, registry_loader, patched_api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [],
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [],
        },
        "accounts.buyers": {
            "path": "/public/v1/accounts/buyers",
            "summary": "Buyers",
            "parameters": [],
        },
    }
    registry_loader.return_value = mock_registry

    with pytest.raises(ToolError, match=r"Unknown resource: 'catalog\.product'") as error:
        await marketplace_query("catalog.product", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert "catalog.products" in details["did_you_mean"]


async def test_unknown_resource_shows_categories(call_context, registry_loader, patched_api_client):
    mock_registry = {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [],
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "Orders",
            "parameters": [],
        },
    }
    registry_loader.return_value = mock_registry

    with pytest.raises(ToolError) as error:
        await marketplace_query("invalid.resource", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert sorted(details["available_categories"]) == ["catalog", "commerce"]


@pytest.mark.parametrize(
    ("path", "resource", "expected_example"),
    [
        (
            "/public/v1/catalog/products/{id}",
            "catalog.products.by_id",
            (
                "marketplace_query(resource='catalog.products.by_id', "
                "path_params={'id': 'PRD-1234-5678'}, limit=10)"
            ),
        ),
        (
            "/public/v1/commerce/orders/{orderId}",
            "commerce.orders.by_id",
            (
                "marketplace_query(resource='commerce.orders.by_id', "
                "path_params={'orderId': 'ORD-1234-5678-9012'}, limit=10)"
            ),
        ),
    ],
)
async def test_missing_path_params_shows_example(
    call_context, registry_loader, patched_api_client, path, resource, expected_example
):
    registry_loader.return_value = {
        resource: {"path": path, "parameters": [{"in": "path", "required": True}]}
    }

    with pytest.raises(ToolError, match="requires path parameters") as error:
        await marketplace_query(resource, call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["example"] == expected_example
    assert "hint" in details


@pytest.mark.parametrize(
    ("status", "response_body", "expected_details"),
    [
        (
            HTTPStatus.BAD_REQUEST,
            {"message": "Invalid RQL", "field": "rql"},
            {
                "status_code": HTTPStatus.BAD_REQUEST,
                "api_error_details": {"message": "Invalid RQL", "field": "rql"},
            },
        ),
        (
            HTTPStatus.NOT_FOUND,
            ValueError("Not JSON"),
            {
                "status_code": HTTPStatus.NOT_FOUND,
                "request_url": "https://api.test.com/public/v1/catalog/products",
            },
        ),
    ],
)
async def test_api_error_includes_details(
    call_context, registry_loader, patched_api_client, status, response_body, expected_details
):
    registry_loader.return_value = {
        "catalog.products": {"path": "/public/v1/catalog/products", "parameters": []}
    }
    mock_response = Mock(spec=httpx.Response, status_code=status, text=status.phrase)
    mock_response.json.side_effect = response_body if isinstance(response_body, Exception) else None
    mock_response.json.return_value = response_body
    mock_request = Mock(spec=httpx.Request, url="https://api.test.com/public/v1/catalog/products")
    http_error = httpx.HTTPStatusError(
        f"{status.value} {status.phrase}", request=mock_request, response=mock_response
    )
    patched_api_client.get = AsyncMock(side_effect=http_error)

    with pytest.raises(ToolError, match=f"{status.value} {status.phrase}") as error:
        await marketplace_query("catalog.products", call_context=call_context)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert {key: details[key] for key in expected_details} == expected_details
