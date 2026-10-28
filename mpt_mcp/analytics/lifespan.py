import logging
from typing import TYPE_CHECKING, Any

from fastmcp.server.lifespan import lifespan

from mpt_mcp.analytics.logger import initialize_analytics
from mpt_mcp.config import config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@lifespan
async def analytics_lifespan(server: Any) -> AsyncIterator[dict[str, Any]]:
    """Run the analytics logger inside the server's event loop and flush pending events on shutdown."""
    analytics = await initialize_analytics(database_url=config.analytics_database_url)
    logger.info(
        "📊 Analytics enabled - tracking usage metrics"
        if analytics.enabled
        else "📊 Analytics disabled (no database configured)"
    )
    try:
        yield {}
    finally:
        await analytics.close()
