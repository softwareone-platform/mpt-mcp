from typing import TYPE_CHECKING, Any

from fastmcp.server.lifespan import lifespan

from mpt_mcp.analytics.logger import ANALYTICS_KEY, AnalyticsLogger
from mpt_mcp.config import config

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@lifespan
async def analytics_lifespan(server: Any) -> AsyncIterator[dict[str, Any]]:
    """Give the server an analytics logger in its event loop, closed on shutdown."""
    analytics_logger = AnalyticsLogger(database_url=config.analytics_database_url)
    await analytics_logger.initialize()
    try:
        yield {ANALYTICS_KEY: analytics_logger}
    finally:
        await analytics_logger.close()
