from unittest.mock import AsyncMock, patch

from fastmcp import FastMCP

from mpt_mcp.analytics.lifespan import analytics_lifespan


async def test_lifespan_closes_logger_on_shutdown():
    analytics_logger = AsyncMock(enabled=True)
    server = FastMCP("test")

    with patch(
        "mpt_mcp.analytics.lifespan.initialize_analytics",
        new_callable=AsyncMock,
        return_value=analytics_logger,
    ):
        async with analytics_lifespan(server):
            pass  # act

    analytics_logger.close.assert_awaited_once()
