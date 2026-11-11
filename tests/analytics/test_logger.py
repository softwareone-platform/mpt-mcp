import logging
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import Context
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from mpt_mcp.analytics.events import AnalyticsContext, ApiQueryEvent, ToolCallEvent
from mpt_mcp.analytics.logger import (
    ANALYTICS_KEY,
    SERVER_VERSION,
    AnalyticsLogger,
    current_analytics_context,
    get_analytics_logger,
)

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/db"


@pytest.fixture
def connection():
    return AsyncMock()


@pytest.fixture
def analytics_logger(connection):
    transaction = AsyncMock()
    transaction.__aenter__.return_value = connection
    analytics_logger = AnalyticsLogger(database_url=DATABASE_URL)
    analytics_logger.engine = Mock(spec=AsyncEngine, begin=Mock(return_value=transaction))
    return analytics_logger


@pytest.fixture
def caller_context():
    analytics_context = AnalyticsContext(
        token_id="TKN-1234-5678", api_endpoint="https://api.s1.show", session_id="abc"
    )
    context_token = current_analytics_context.set(analytics_context)
    yield analytics_context
    current_analytics_context.reset(context_token)


async def test_flush_inserts_event_with_context(analytics_logger, connection, caller_context):
    await analytics_logger.record(ToolCallEvent(tool_name="marketplace_query", response_time_ms=10))

    await analytics_logger.flush()  # act

    inserted_events = connection.execute.await_args.args[1]
    inserted_event = inserted_events[0]
    assert inserted_event | {"timestamp": None} == {
        "tool_name": "marketplace_query",
        "response_time_ms": 10,
        "error_type": None,
        "error_message": None,
        "event_type": "tool_call",
        "token_id": "TKN-1234-5678",
        "api_endpoint": "https://api.s1.show",
        "client_info": None,
        "client_ip": None,
        "session_id": "abc",
        "timestamp": None,
        "server_type": "http",
        "server_version": SERVER_VERSION,
    }
    assert inserted_event["timestamp"].tzinfo is None


async def test_record_flushes_full_batch(connection):
    transaction = AsyncMock()
    transaction.__aenter__.return_value = connection
    analytics_logger = AnalyticsLogger(database_url=DATABASE_URL, batch_size=1)
    analytics_logger.engine = Mock(spec=AsyncEngine, begin=Mock(return_value=transaction))

    await analytics_logger.record(ToolCallEvent(tool_name="marketplace_query"))  # act

    connection.execute.assert_awaited_once()


async def test_record_skipped_when_disabled(analytics_logger, connection):
    analytics_logger.enabled = False
    await analytics_logger.record(ToolCallEvent(tool_name="marketplace_query"))

    await analytics_logger.flush()  # act

    connection.execute.assert_not_awaited()


async def test_record_logs_failure(analytics_logger, caplog):
    event = ApiQueryEvent(
        api_resource="commerce.orders",
        api_path="/public/v1/commerce/orders",
        api_status_code=HTTPStatus.NOT_FOUND,
        api_response_time_ms=0,
    )

    with caplog.at_level(logging.WARNING, logger="mpt_mcp.analytics.logger"):
        await analytics_logger.record(event)  # act

    assert caplog.messages == ["API: commerce.orders | Token: None | Error: 404"]


async def test_flush_drops_events_on_database_error(analytics_logger, connection):
    connection.execute.side_effect = OperationalError("INSERT", {}, Exception("down"))
    await analytics_logger.record(ToolCallEvent(tool_name="marketplace_query"))

    await analytics_logger.flush()  # act

    connection.execute.side_effect = None
    await analytics_logger.flush()
    connection.execute.assert_awaited_once()


@pytest.mark.parametrize("database_url", [None, ""])
async def test_initialize_skips_engine_without_url(database_url):
    analytics_logger = AnalyticsLogger(database_url=database_url)

    with patch("mpt_mcp.analytics.logger.create_async_engine") as create_engine:
        await analytics_logger.initialize()  # act

    create_engine.assert_not_called()


async def test_initialize_disables_on_connection_error():
    analytics_logger = AnalyticsLogger(database_url=DATABASE_URL)
    engine = Mock(spec=AsyncEngine, begin=Mock(side_effect=ConnectionRefusedError("refused")))

    with patch("mpt_mcp.analytics.logger.create_async_engine", return_value=engine):
        await analytics_logger.initialize()  # act

    assert analytics_logger.enabled is False


@pytest.mark.parametrize(
    ("lifespan_context", "expected"),
    [({ANALYTICS_KEY: "analytics"}, "analytics"), ({}, None)],
)
def test_get_analytics_logger(lifespan_context, expected):
    context = Mock(spec=Context, lifespan_context=lifespan_context)

    result = get_analytics_logger(context)

    assert result == expected
