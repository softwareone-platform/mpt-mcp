from unittest.mock import patch

from fastmcp import FastMCP

from mpt_mcp.analytics.lifespan import analytics_lifespan
from mpt_mcp.analytics.logger import ANALYTICS_KEY, AnalyticsLogger
from mpt_mcp.config import config


async def test_lifespan_gives_logger(monkeypatch):
    monkeypatch.setattr(config, "analytics_database_url", "")

    async with analytics_lifespan(FastMCP("test")) as lifespan_context:
        result = lifespan_context[ANALYTICS_KEY]

    assert isinstance(result, AnalyticsLogger)
    assert result.enabled is False


async def test_lifespan_closes_logger_on_shutdown(monkeypatch):
    monkeypatch.setattr(config, "analytics_database_url", "")

    with patch.object(AnalyticsLogger, "close", autospec=True) as close:
        async with analytics_lifespan(FastMCP("test")):
            pass  # act

    close.assert_awaited_once()
