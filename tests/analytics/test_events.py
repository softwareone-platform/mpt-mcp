from http import HTTPStatus

import pytest

from mpt_mcp.analytics.events import (
    ApiQueryEvent,
    PromptGetEvent,
    ResourceReadEvent,
    ToolCallEvent,
)

API_RESPONSE_TIME_MS = 120
RESPONSE_TIME_MS = 250


@pytest.fixture
def api_query_factory():
    def factory(status_code):
        return ApiQueryEvent(
            api_resource="commerce.orders",
            api_path="/public/v1/commerce/orders",
            api_status_code=status_code,
            api_response_time_ms=API_RESPONSE_TIME_MS,
        )

    return factory


@pytest.mark.parametrize(
    ("event", "event_type", "subject"),
    [
        (ToolCallEvent(tool_name="marketplace_query"), "tool_call", "marketplace_query"),
        (PromptGetEvent(tool_name="recent_orders"), "prompt_get", "recent_orders"),
        (
            ResourceReadEvent(resource_uri="api://openapi.json"),
            "resource_read",
            "api://openapi.json",
        ),
    ],
)
def test_successful_event(event, event_type, subject):
    result = (event.event_type, event.subject, event.failure)

    assert result == (event_type, subject, None)


def test_failed_event_is_error():
    event = ToolCallEvent(tool_name="marketplace_query", error_message="")

    result = event.event_type

    assert result == "error"


def test_tool_call_row():
    event = ToolCallEvent(
        tool_name="marketplace_query",
        response_time_ms=RESPONSE_TIME_MS,
        error_type="tool_error",
        error_message="Missing X-MPT-Authorization header",
    )

    result = event.to_row()

    assert result == {
        "tool_name": "marketplace_query",
        "response_time_ms": RESPONSE_TIME_MS,
        "error_type": "tool_error",
        "error_message": "Missing X-MPT-Authorization header",
        "event_type": "error",
    }


def test_api_query_succeeds(api_query_factory):
    event = api_query_factory(HTTPStatus.OK)

    result = (event.event_type, event.failure, event.elapsed_ms, event.subject)

    assert result == ("api_query", None, API_RESPONSE_TIME_MS, "commerce.orders")


def test_api_query_fails_on_status(api_query_factory):
    event = api_query_factory(HTTPStatus.NOT_FOUND)

    result = (event.event_type, event.failure)

    assert result == ("api_query", "404")


def test_api_query_row(api_query_factory):
    event = api_query_factory(HTTPStatus.OK)

    result = event.to_row()

    assert result["api_method"] == "GET"
    assert result["tool_name"] == "marketplace_query"
    assert result["response_time_ms"] is None
    assert result["api_response_time_ms"] == API_RESPONSE_TIME_MS
