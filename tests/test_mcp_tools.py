import json
import logging
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp.exceptions import ToolError
from httpx import HTTPStatusError, Request, Response

from mpt_mcp.audit_fields import FALLBACK_STATIC_REGEX
from mpt_mcp.mcp_tools import (
    CHARACTER_LIMIT,
    execute_marketplace_query,
    execute_marketplace_resource_info,
    execute_marketplace_resource_schema,
    execute_marketplace_resources,
    fit_result_to_budget,
    suggest_resources,
    tool_error,
)

PRODUCTS_PAGE_SIZE = 10

QUERY_LIMIT = 50

PAGE_OFFSET = 20

# Resources that make the marketplace_resources list longer than one result
LONG_REGISTRY_SIZE = 300
LONG_CATEGORY_SIZE = 80

AUDIT_RQL = 'gt(audit.created.at,"2026-01-22T00:00:00Z")'

DATE_RANGE_RQL = (
    'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),lt(audit.created.at,"2026-01-22T23:59:59Z"))'
)

QUERY_DEFAULTS = {
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
def send_query(api_client, endpoints_registry, orders_with_audit_response):
    async def _send_query(response=None, **query_args):
        api_client.get.return_value = response or orders_with_audit_response
        await execute_marketplace_query(
            **{**QUERY_DEFAULTS, **query_args},
            api_client=api_client,
            endpoints_registry=endpoints_registry,
        )
        return api_client.get.call_args.kwargs["query_params"]

    return _send_query


@pytest.fixture
def send_select(send_query):
    async def _send_select(**query_args):
        query_params = await send_query(**query_args)
        select = query_params.get("select", "")
        return [part.lstrip("+") for part in select.split(",")] if select else []

    return _send_select


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
    api_client, orders_with_audit_response, endpoints_registry
):
    error_response = Response(
        HTTPStatus.BAD_REQUEST,
        json={"errors": {"select": ["Invalid field"]}},
        request=Request("GET", "https://api.test.com/test"),
    )
    http_error = HTTPStatusError(
        "400 Bad Request", request=error_response.request, response=error_response
    )
    api_client.get = AsyncMock(side_effect=[http_error, orders_with_audit_response])

    await execute_marketplace_query(  # act
        **{**QUERY_DEFAULTS, "rql": AUDIT_RQL, "select": "+id,+name"},
        api_client=api_client,
        endpoints_registry=endpoints_registry,
    )

    sent_params = [call.kwargs["query_params"] for call in api_client.get.call_args_list]
    sent_selects = [query_params["select"] for query_params in sent_params]
    assert "audit" in sent_selects[0]
    assert "audit" not in sent_selects[1]
    assert {"+id", "+name"} <= set(sent_selects[1].split(","))


async def test_returns_api_response(api_client, products_page_response, endpoints_registry):
    api_client.get.return_value = products_page_response

    result = await execute_marketplace_query(
        **{**QUERY_DEFAULTS, "resource": "catalog.products"},
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
    with caplog.at_level(logging.INFO, logger="mpt_mcp.mcp_tools"):
        await send_query(  # act
            response=products_page_response, resource="catalog.products", limit=None
        )

    assert "default limit=10" in caplog.text.lower()


async def test_catalog_products_default_select(send_query, products_page_response):
    result = await send_query(response=products_page_response, resource="catalog.products")

    assert result["select"] == "-*,+id,+name,+shortDescription"


@pytest.fixture
def orders_response():
    return {
        "data": [{"id": "ord-1", "status": "Created", "audit": {}}],
        "$meta": {"pagination": {"total": 1, "limit": 100, "offset": 0}},
    }


async def test_sanitizes_select_drops_invalid_adds_id(send_select, openapi_spec, orders_response):
    result = await send_select(
        response=orders_response, select="audit,status,orderNumber", openapi_spec=openapi_spec
    )

    assert {"id", "audit", "status"} <= set(result)
    assert "orderNumber" not in result


async def test_select_without_openapi_spec_adds_id(send_select, orders_response):
    result = await send_select(response=orders_response, select="audit,status")

    assert {"id", "audit", "status"} <= set(result)


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

    select_doc = result["common_parameters"]["select"]
    assert "select=-*,+id,+name" in select_doc
    assert "$meta.omitted" in select_doc


@pytest.fixture
def resources_registry():
    return {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "List products",
            "description": "Products of the catalog",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Draft", "Published"]}}
            ],
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "summary": "List orders",
            "parameters": [],
        },
        "commerce.orders.by_id": {
            "path": "/public/v1/commerce/orders/{id}",
            "summary": "Get an order",
            "parameters": [{"name": "id", "in": "path"}],
        },
    }


def test_resources_lists_names_and_summaries(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com", user_id=None, endpoints_registry=resources_registry
    )

    assert result["categories"] == {
        "catalog": [{"resource": "catalog.products", "summary": "List products"}],
        "commerce": [
            {"resource": "commerce.orders", "summary": "List orders"},
            {"resource": "commerce.orders.by_id", "summary": "Get an order"},
        ],
    }


def test_resources_category_adds_details(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com",
        user_id=None,
        endpoints_registry=resources_registry,
        category="catalog",
    )

    assert result["categories"] == {
        "catalog": [
            {
                "resource": "catalog.products",
                "summary": "List products",
                "path": "/public/v1/catalog/products",
                "description": "Products of the catalog",
                "filterable_fields": ["status"],
                "enum_fields": {"status": ["Draft", "Published"]},
            }
        ]
    }


def test_resources_search_matches_name_or_summary(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com",
        user_id=None,
        endpoints_registry=resources_registry,
        search="ORDER",
    )

    assert result["total_resources"] == 2
    assert list(result["categories"]) == ["commerce"]


@pytest.fixture
def long_registry():
    summary = "x" * 100
    endpoint_info = {"path": "/public/v1/commerce/resource", "summary": summary}
    endpoint_info.update(description=summary, parameters=[])
    resource_names = [f"commerce.resource{index}" for index in range(LONG_REGISTRY_SIZE)]
    return dict.fromkeys(resource_names, endpoint_info)


def test_resources_long_list_keeps_names(long_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com", user_id=None, endpoints_registry=long_registry
    )

    entries = result["categories"]["commerce"]
    assert len(json.dumps(result)) <= CHARACTER_LIMIT
    assert len(entries) == LONG_REGISTRY_SIZE
    assert entries[0] == {"resource": "commerce.resource0"}
    assert "category or search" in result["note"]


def test_resources_long_category_keeps_summaries(long_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com",
        user_id=None,
        endpoints_registry=dict(list(long_registry.items())[:LONG_CATEGORY_SIZE]),
        category="commerce",
    )

    entries = result["categories"]["commerce"]
    assert entries[0] == {"resource": "commerce.resource0", "summary": "x" * 100}
    assert "marketplace_resource_info" in result["note"]


def test_resources_short_list_has_no_note(resources_registry):
    result = execute_marketplace_resources(
        api_base_url="https://api.test.com", user_id=None, endpoints_registry=resources_registry
    )

    assert "note" not in result


def test_resources_unknown_category_fails(resources_registry):
    with pytest.raises(ToolError, match="Unknown category: commrce") as error:
        execute_marketplace_resources(
            api_base_url="https://api.test.com",
            user_id=None,
            endpoints_registry=resources_registry,
            category="commrce",
        )

    _, error_details = str(error.value).split("\n", 1)
    assert json.loads(error_details) == {"available_categories": ["catalog", "commerce"]}


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
    with pytest.raises(ToolError, match=r"Unknown resource: unknown\.resource"):
        execute_marketplace_resource_info(
            resource="unknown.resource",
            endpoints_registry=endpoints_registry,
        )


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


def test_resource_schema_lists_item_fields(endpoints_registry, openapi_spec_with_fields):
    result = execute_marketplace_resource_schema(
        resource="commerce.orders",
        openapi_spec=openapi_spec_with_fields(["id", "status"]),
        endpoints_registry=endpoints_registry,
    )

    assert list(result["fields"]) == ["id", "status"]


def test_resource_schema_resolves_field_refs(endpoints_registry):
    order_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "audit": {"allOf": [{"$ref": "#/components/schemas/Audit"}]},
        },
    }
    list_schema = {"properties": {"data": {"type": "array", "items": {"$ref": "#/order"}}}}
    response = {"200": {"content": {"application/json": {"schema": list_schema}}}}
    openapi_spec = {
        "order": order_schema,
        "components": {"schemas": {"Audit": {"properties": {"created": {"type": "object"}}}}},
        "paths": {"/public/v1/commerce/orders": {"get": {"responses": response}}},
    }

    result = execute_marketplace_resource_schema(
        resource="commerce.orders", openapi_spec=openapi_spec, endpoints_registry=endpoints_registry
    )

    assert result["fields"]["audit"]["type"] == "object"
    assert result["filtering_hints"]["simple_filters"] == ["eq(id,value)"]


@pytest.fixture
def sent_select(api_client, endpoints_registry, orders_response, openapi_spec_with_fields):
    async def _sent_select(select, fields):
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


def test_tool_error_without_details():
    result = tool_error("Unknown resource: x")

    assert str(result) == "Unknown resource: x"


def test_tool_error_appends_details_as_json():
    result = tool_error("Unknown resource: x", did_you_mean=["catalog.products"])

    assert str(result) == 'Unknown resource: x\n{"did_you_mean": ["catalog.products"]}'


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


def big_page(item_count):
    return {
        "$meta": {"pagination": {"offset": PAGE_OFFSET, "limit": item_count, "total": 500}},
        "data": [{"id": f"ORD-{index}", "notes": "x" * 1000} for index in range(item_count)],
    }


def test_fit_result_keeps_short_page():
    page = big_page(3)

    result = fit_result_to_budget(page, offset=PAGE_OFFSET)

    assert result == page


def test_fit_result_cuts_long_page():
    page = big_page(100)

    result = fit_result_to_budget(page, offset=PAGE_OFFSET)

    returned = len(result["data"])
    assert 0 < returned < 100
    assert len(json.dumps(result)) <= CHARACTER_LIMIT
    assert result["data"] == page["data"][:returned]
    assert result["$meta"]["pagination"] == page["$meta"]["pagination"]
    assert result["$meta"]["truncated"]["next_offset"] == PAGE_OFFSET + returned
    assert result["$meta"]["truncated"]["requested"] == 100


def test_fit_result_ignores_single_item():
    order = {"id": "ORD-1", "notes": "x" * (CHARACTER_LIMIT * 2)}

    result = fit_result_to_budget(order, offset=None)

    assert result == order


def test_fit_result_too_long_item_fails():
    page = {"data": [{"id": "ORD-1", "notes": "x" * (CHARACTER_LIMIT * 2)}]}

    with pytest.raises(ToolError, match="One item takes more than"):
        fit_result_to_budget(page, offset=0)
