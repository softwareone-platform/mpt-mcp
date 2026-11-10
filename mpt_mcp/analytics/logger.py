import asyncio
import contextlib
import datetime as dt
import logging
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any

from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from sqlalchemy import insert, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mpt_mcp.analytics.events import AnalyticsContext, McpEvent
from mpt_mcp.analytics.models import mcp_events

ANALYTICS_KEY = "analytics"
# Errors of the database connection and of its driver, which reach us unwrapped
DATABASE_ERRORS = (SQLAlchemyError, OSError)
SERVER_TYPE = "http"
SERVER_VERSION = "1.0.0"

logger = logging.getLogger(__name__)

# Caller of the current MCP request, set by AnalyticsMiddleware
current_analytics_context: ContextVar[AnalyticsContext] = ContextVar(
    "analytics_context", default=AnalyticsContext()
)


class AnalyticsLogger:
    """Records MCP events in mcp_events, inserted in batches by a background task."""

    def __init__(
        self, database_url: str | None = None, batch_size: int = 50, flush_interval: float = 5.0
    ):
        """
        Initialize analytics logger.

        Args:
            database_url: PostgreSQL connection string (e.g., postgresql+asyncpg://user:pass@host/db)
            batch_size: Number of events to batch before inserting
            flush_interval: Seconds between automatic flushes
        """
        self.database_url = database_url
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.engine: AsyncEngine | None = None
        self.enabled = bool(database_url)
        self._event_queue: list[dict[str, Any]] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Stop the background flush, insert the pending events and close the connection."""
        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        await self.flush()

        if self.engine:
            await self.engine.dispose()
            logger.info("Analytics logger closed")

    async def flush(self) -> None:
        """Insert the pending events; a failed insert drops them instead of retrying."""
        if not self.enabled or not self.engine:
            return

        async with self._lock:
            if not self._event_queue:
                return

            events_to_insert = list(self._event_queue)
            self._event_queue.clear()

        try:
            async with self.engine.begin() as conn:
                await conn.execute(insert(mcp_events), events_to_insert)
        except DATABASE_ERRORS:
            logger.exception("Failed to flush %s events", len(events_to_insert))
            return

        logger.debug("Flushed %s events to database", len(events_to_insert))

    async def initialize(self) -> None:
        """Connect to the database and start the background flush, or disable analytics."""
        database_url = self.database_url
        if not self.enabled or not database_url:
            logger.info("Analytics disabled (no database URL configured)")
            return

        try:
            self.engine = create_async_engine(
                database_url, pool_size=5, max_overflow=10, echo=False
            )
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
        except DATABASE_ERRORS:
            logger.exception("Failed to initialize analytics")
            self.enabled = False
            return

        logger.info("Analytics enabled - connected to database")
        self._flush_task = asyncio.create_task(self._background_flush())

    async def record(self, event: McpEvent) -> None:
        """
        Queue an event with the caller of the current request, and log it to the console.

        Args:
            event: Event of the MCP call
        """
        if not self.enabled:
            return

        context = current_analytics_context.get()
        # The timestamp column has no time zone, so store naive UTC (asyncpg rejects aware
        # datetimes)
        timestamp = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        row = {
            **event.to_row(),
            **asdict(context),
            "timestamp": timestamp,
            "server_type": SERVER_TYPE,
            "server_version": SERVER_VERSION,
        }
        async with self._lock:
            self._event_queue.append(row)
            should_flush = len(self._event_queue) >= self.batch_size

        if should_flush:
            await self.flush()

        failure = event.failure
        if failure is None:
            logger.info(
                "%s: %s | Token: %s | %sms",
                event.log_label,
                event.subject,
                context.token_id,
                event.elapsed_ms,
            )
        else:
            logger.warning(
                "%s: %s | Token: %s | Error: %s",
                event.log_label,
                event.subject,
                context.token_id,
                failure,
            )

    async def _background_flush(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            await self.flush()


def get_analytics_logger(context: Context = CurrentContext()) -> AnalyticsLogger | None:  # noqa: WPS404
    """
    Return the analytics logger of the server, created by analytics_lifespan.

    Args:
        context: Context of the MCP request, injected by FastMCP

    Returns:
        Analytics logger, or None on servers without analytics (stdio)
    """
    analytics_logger: AnalyticsLogger | None = context.lifespan_context.get(ANALYTICS_KEY)
    return analytics_logger
