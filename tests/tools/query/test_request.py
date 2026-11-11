import json
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.analytics import AnalyticsLogger
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.tools.query.request import MarketplaceRequest

AUDIT_SELECT = "id,+audit.created.at"


@pytest.fixture
def api_client():
    return Mock(spec=APIClient, get=AsyncMock())


@pytest.fixture
def analytics_logger():
    return Mock(spec=AnalyticsLogger, record=AsyncMock())


@pytest.fixture
def request_factory(api_client):
    def factory(api_path="/public/v1/commerce/orders", analytics_logger=None):
        return MarketplaceRequest("commerce.orders", api_path, api_client, analytics_logger)

    return factory


@pytest.fixture
def failed_send_factory(api_client, request_factory, query_params_factory):
    async def factory(api_error, analytics_logger=None):
        api_client.get = AsyncMock(side_effect=api_error)
        return await request_factory(analytics_logger=analytics_logger).send(
            query_params_factory(), None
        )

    return factory


@pytest.fixture
def orders_page():
    return {
        "data": [{"id": "ORD-123", "status": "Completed"}],
        "$meta": {"pagination": {"total": 1, "limit": 10, "offset": 0}},
    }


async def test_send_returns_api_response(api_client, request_factory, query_params_factory):
    api_client.get.return_value = {"data": [{"id": "ORD-1"}]}

    result = await request_factory().send(query_params_factory(rql="eq(status,Active)"), None)

    assert result == {"data": [{"id": "ORD-1"}]}
    assert api_client.get.call_args.kwargs["query_params"] == {
        "rql": "eq(status,Active)",
        "limit": 10,
    }


async def test_retries_with_fallback_on_bad_request(
    api_client, request_factory, query_params_factory, http_error_factory, orders_page
):
    http_error = http_error_factory(HTTPStatus.BAD_REQUEST, {"errors": {"select": ["Invalid"]}})
    api_client.get = AsyncMock(side_effect=[http_error, orders_page])

    result = await request_factory().send(
        query_params_factory(select=AUDIT_SELECT), query_params_factory(select="+id,+name")
    )

    sent_selects = [call.kwargs["query_params"]["select"] for call in api_client.get.call_args_list]
    assert sent_selects == [AUDIT_SELECT, "+id,+name"]
    assert result == orders_page


async def test_failed_retry_reports_first_error(
    api_client, request_factory, query_params_factory, http_error_factory
):
    first_error = http_error_factory(HTTPStatus.BAD_REQUEST, {"message": "Invalid select"})
    retry_error = http_error_factory(HTTPStatus.NOT_FOUND, ValueError("Not JSON"))
    api_client.get = AsyncMock(side_effect=[first_error, retry_error])
    query_request = request_factory()
    audit_query = query_params_factory(select=AUDIT_SELECT)
    fallback_query = query_params_factory()

    with pytest.raises(ToolError) as error:
        await query_request.send(audit_query, fallback_query)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["status_code"] == HTTPStatus.BAD_REQUEST
    assert details["api_error_details"] == {"message": "Invalid select"}


@pytest.mark.parametrize("status", [HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND])
async def test_sends_once_without_fallback_retry(
    api_client, request_factory, query_params_factory, http_error_factory, status
):
    api_client.get = AsyncMock(side_effect=http_error_factory(status, {"message": "Failed"}))
    fallback_query = query_params_factory() if status == HTTPStatus.NOT_FOUND else None
    query_request = request_factory()
    query_params = query_params_factory()

    with pytest.raises(ToolError):
        await query_request.send(query_params, fallback_query)

    api_client.get.assert_awaited_once()


async def test_obfuscates_api_token_values(api_client, request_factory, query_params_factory):
    api_client.get.return_value = {"data": [{"id": "TKN-1", "token": "secret"}]}

    result = await request_factory(api_path="/public/v1/accounts/api-tokens").send(
        query_params_factory(), None
    )

    assert result == {"data": [{"id": "TKN-1", "token": "[REDACTED]"}]}


async def test_records_sent_query_in_analytics(
    api_client, analytics_logger, request_factory, query_params_factory, orders_page
):
    api_client.get.return_value = orders_page

    await request_factory(analytics_logger=analytics_logger).send(  # act
        query_params_factory(select=AUDIT_SELECT), None
    )

    recorded = analytics_logger.record.call_args.args[0]
    assert recorded.api_status_code == HTTPStatus.OK
    assert recorded.result_count == 1
    assert recorded.select_fields == AUDIT_SELECT


async def test_records_api_error_in_analytics(
    analytics_logger, failed_send_factory, http_error_factory
):
    http_error = http_error_factory(HTTPStatus.NOT_FOUND, ValueError("Not JSON"))

    with pytest.raises(ToolError):
        await failed_send_factory(http_error, analytics_logger=analytics_logger)

    recorded = analytics_logger.record.call_args.args[0]
    assert recorded.api_status_code == HTTPStatus.NOT_FOUND
    assert recorded.result_count is None


async def test_records_invalid_response_in_analytics(analytics_logger, failed_send_factory):
    invalid_response = ValueError("Response is not JSON")

    with pytest.raises(ToolError):
        await failed_send_factory(invalid_response, analytics_logger=analytics_logger)

    recorded = analytics_logger.record.call_args.args[0]
    assert recorded.api_status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert recorded.result_count is None


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
                "api_error_text": "Not Found",
            },
        ),
        (
            HTTPStatus.BAD_REQUEST,
            {"errors": {"rql": ["Unknown expression group: audit.shipped.at"]}},
            {
                "hint": (
                    "The resource does not have this audit field: list its audit events with "
                    "marketplace_audit_fields(resource)"
                ),
            },
        ),
        (
            HTTPStatus.BAD_REQUEST,
            {"errors": {"audit.shipped": ["Invalid property path."]}},
            {
                "hint": (
                    "The resource does not have this audit field: list its audit events with "
                    "marketplace_audit_fields(resource)"
                ),
            },
        ),
    ],
)
async def test_api_error_includes_details(
    failed_send_factory, http_error_factory, status, response_body, expected_details
):
    http_error = http_error_factory(status, response_body)

    with pytest.raises(ToolError, match=f"{status.value} {status.phrase}") as error:
        await failed_send_factory(http_error)

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert {key: details[key] for key in expected_details} == expected_details


async def test_invalid_path_without_audit_has_no_hint(failed_send_factory, http_error_factory):
    http_error = http_error_factory(
        HTTPStatus.BAD_REQUEST, {"errors": {"notAField": ["Invalid property path."]}}
    )

    with pytest.raises(ToolError) as error:
        await failed_send_factory(http_error)

    _, error_details = str(error.value).split("\n", 1)
    assert "hint" not in json.loads(error_details)
