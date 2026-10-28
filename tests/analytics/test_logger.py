from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mpt_mcp.analytics.logger import AnalyticsLogger


@pytest.fixture
def connection():
    return AsyncMock()


@pytest.fixture
def analytics_logger(connection):
    @asynccontextmanager
    async def begin():
        yield connection

    analytics_logger = AnalyticsLogger(database_url="postgresql+asyncpg://user:pass@localhost/db")
    analytics_logger.engine = Mock(begin=begin)
    return analytics_logger


async def test_flush_stores_naive_utc_timestamps(analytics_logger, connection):
    await analytics_logger.log_tool_call(tool_name="marketplace_query", response_time_ms=10)

    await analytics_logger.flush()  # act

    inserted_events = connection.execute.await_args.args[1]
    assert inserted_events[0]["timestamp"].tzinfo is None


@pytest.mark.parametrize("database_url", [None, ""])
async def test_initialize_skips_engine_without_url(database_url):
    analytics_logger = AnalyticsLogger(database_url=database_url)

    with patch("mpt_mcp.analytics.logger.create_async_engine") as create_engine:
        await analytics_logger.initialize()  # act

    create_engine.assert_not_called()
