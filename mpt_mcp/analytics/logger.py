import asyncio
import contextlib
import datetime as dt
import logging
from contextvars import ContextVar
from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mpt_mcp.analytics.models import mcp_events
from mpt_mcp.token_validator import parse_token_id

logger = logging.getLogger(__name__)

# Context variables for tracking request context
_current_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_current_token_id: ContextVar[str | None] = ContextVar("token_id", default=None)
_current_api_endpoint: ContextVar[str | None] = ContextVar("api_endpoint", default=None)
_current_client_info: ContextVar[str | None] = ContextVar("client_info", default=None)
_current_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


class AnalyticsLogger:
    """
    Async analytics logger for MCP server.

    Features:
    - Non-blocking batch inserts
    - Automatic session tracking
    - Error pattern detection
    - Popular query tracking
    - Privacy-safe (no account data)
    """

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
        self._flush_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.server_version = "1.0.0"

    async def initialize(self):
        """Initialize database connection and start background flush task."""
        if not self.enabled:
            logger.info("📊 Analytics disabled (no database URL configured)")
            return

        try:
            self.engine = create_async_engine(
                self.database_url, pool_size=5, max_overflow=10, echo=False
            )

            # Test connection
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))

            logger.info("📊 Analytics enabled - connected to database")

            # Start background flush task
            self._flush_task = asyncio.create_task(self._background_flush())

        except Exception:
            logger.exception("❌ Failed to initialize analytics")
            self.enabled = False

    async def close(self):
        """Close database connection and flush remaining events."""
        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        # Flush remaining events
        await self.flush()

        if self.engine:
            await self.engine.dispose()
            logger.info("📊 Analytics logger closed")

    async def _background_flush(self):
        """Background task that periodically flushes events to database."""
        while True:
            try:
                await asyncio.sleep(self.flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                raise  # Re-raise so the task is properly cancelled
            except Exception:
                logger.exception("❌ Error in background flush")

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Ensure event has all required columns for database insertion."""
        # Define all table columns with default None values
        timestamp = event.get("timestamp")
        return {
            # The timestamp column has no time zone, so store naive UTC (asyncpg rejects aware
            # datetimes)
            "timestamp": timestamp.astimezone(dt.UTC).replace(tzinfo=None) if timestamp else None,
            "response_time_ms": event.get("response_time_ms"),
            "token_id": event.get("token_id"),
            "api_endpoint": event.get("api_endpoint"),
            "session_id": event.get("session_id"),
            "event_type": event.get("event_type"),
            "server_type": event.get("server_type"),
            "tool_name": event.get("tool_name"),
            "resource_uri": event.get("resource_uri"),
            "api_resource": event.get("api_resource"),
            "api_path": event.get("api_path"),
            "api_method": event.get("api_method"),
            "api_status_code": event.get("api_status_code"),
            "api_response_time_ms": event.get("api_response_time_ms"),
            "result_count": event.get("result_count"),
            "rql_filter": event.get("rql_filter"),
            "limit_value": event.get("limit_value"),
            "offset_value": event.get("offset_value"),
            "order_by": event.get("order_by"),
            "select_fields": event.get("select_fields"),
            "cache_hit": event.get("cache_hit"),
            "cache_type": event.get("cache_type"),
            "error_type": event.get("error_type"),
            "error_message": event.get("error_message"),
            "error_details": event.get("error_details"),
            "server_version": event.get("server_version"),
            "client_info": event.get("client_info"),
            "client_ip": event.get("client_ip"),
        }

    async def flush(self):
        """Flush all pending events to database."""
        if not self.enabled or not self.engine:
            return

        async with self._lock:
            if not self._event_queue:
                return

            events_to_insert = [self._normalize_event(error) for error in self._event_queue]
            self._event_queue.clear()

        try:
            async with self.engine.begin() as conn:
                await conn.execute(insert(mcp_events), events_to_insert)
            logger.debug("📊 Flushed %s events to database", len(events_to_insert))
        except Exception:
            logger.exception("❌ Failed to flush events")
            # Don't put events back in queue to avoid infinite retry loop
            logger.debug("Sample event: %s", events_to_insert[0] if events_to_insert else "None")

    async def _queue_event(self, event: dict[str, Any]):
        """Add event to queue and flush if batch size reached."""
        if not self.enabled:
            return

        async with self._lock:
            self._event_queue.append(event)
            should_flush = len(self._event_queue) >= self.batch_size

        if should_flush:
            await self.flush()

    def _get_context(self) -> dict[str, Any]:
        """Get current request context from context variables."""
        return {
            "session_id": _current_session_id.get(),
            "token_id": _current_token_id.get(),
            "api_endpoint": _current_api_endpoint.get(),
            "client_info": _current_client_info.get(),
            "client_ip": _current_client_ip.get(),
            "server_version": self.server_version,
        }

    # ========================================================================
    # Public API - Event Logging Methods
    # ========================================================================

    async def log_tool_call(
        self,
        tool_name: str,
        response_time_ms: int,
        *,
        success: bool = True,
        result_count: int | None = None,
        cache_hit: bool = False,
        cache_type: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        server_type: str = "http",
    ):
        """
        Log a tool call event.

        Args:
            tool_name: Name of the MCP tool called
            response_time_ms: Total response time in milliseconds
            success: Whether the call succeeded
            result_count: Number of results returned
            cache_hit: Whether cache was used
            cache_type: Type of cache (documentation, token, openapi)
            error_type: Type of error if failed
            error_message: Error message if failed
            server_type: http or stdio
        """
        event = {
            **self._get_context(),
            "timestamp": dt.datetime.now(dt.UTC),
            "event_type": "tool_call" if success else "error",
            "server_type": server_type,
            "tool_name": tool_name,
            "response_time_ms": response_time_ms,
            "result_count": result_count,
            "cache_hit": cache_hit,
            "cache_type": cache_type,
            "error_type": error_type,
            "error_message": error_message,
        }

        await self._queue_event(event)

        # Console logging for visibility
        token_id = event.get("token_id", "unknown")
        if success:
            logger.info("📊 Tool: %s | Token: %s | %.0fms", tool_name, token_id, response_time_ms)
        else:
            logger.warning("📊 Tool: %s | Token: %s | Error: %s", tool_name, token_id, error_type)

        # Error patterns are tracked in mcp_events table

    async def log_api_query(
        self,
        api_resource: str,
        api_path: str,
        api_method: str,
        api_status_code: int,
        api_response_time_ms: int,
        result_count: int | None = None,
        rql_filter: str | None = None,
        limit_value: int | None = None,
        offset_value: int | None = None,
        order_by: str | None = None,
        select_fields: str | None = None,
        tool_name: str | None = None,
        server_type: str = "http",
    ):
        """
        Log an API query event.

        Args:
            api_resource: Resource name (e.g., catalog.products)
            api_path: Full API path
            api_method: HTTP method
            api_status_code: HTTP status code
            api_response_time_ms: API response time
            result_count: Number of results returned
            rql_filter: RQL filter used
            limit_value: Limit parameter
            offset_value: Offset parameter
            order_by: Order by parameter
            select_fields: Select fields parameter
            tool_name: Tool that made the query
            server_type: http or stdio
        """
        event = {
            **self._get_context(),
            "timestamp": dt.datetime.now(dt.UTC),
            "event_type": "api_query",
            "server_type": server_type,
            "tool_name": tool_name,
            "api_resource": api_resource,
            "api_path": api_path,
            "api_method": api_method,
            "api_status_code": api_status_code,
            "api_response_time_ms": api_response_time_ms,
            "result_count": result_count,
            "rql_filter": rql_filter,
            "limit_value": limit_value,
            "offset_value": offset_value,
            "order_by": order_by,
            "select_fields": select_fields,
        }

        await self._queue_event(event)

        # Console logging for visibility
        token_id = event.get("token_id", "unknown")
        if api_status_code >= 200 and api_status_code < 300:
            logger.info(
                "📊 API: %s | Token: %s | %s | %.0fms",
                api_resource,
                token_id,
                api_status_code,
                api_response_time_ms,
            )
        else:
            logger.warning("📊 API: %s | Token: %s | %s", api_resource, token_id, api_status_code)

        # Popular queries are tracked in mcp_events table

    async def log_resource_read(
        self,
        resource_uri: str,
        response_time_ms: int,
        *,
        cache_hit: bool = False,
        success: bool = True,
        error_message: str | None = None,
        server_type: str = "http",
    ):
        """
        Log a resource read event (e.g., documentation access).

        Args:
            resource_uri: URI of the resource (e.g., docs://path)
            response_time_ms: Response time
            cache_hit: Whether cache was used
            success: Whether read succeeded
            error_message: Error message if failed
            server_type: http or stdio
        """
        # Determine cache type from resource URI
        cache_type = None
        if cache_hit:
            if resource_uri.startswith("docs://"):
                cache_type = "documentation"
            elif resource_uri.startswith("api://"):
                cache_type = "openapi"

        event = {
            **self._get_context(),
            "timestamp": dt.datetime.now(dt.UTC),
            "event_type": "resource_read" if success else "error",
            "server_type": server_type,
            "resource_uri": resource_uri,
            "response_time_ms": response_time_ms,
            "cache_hit": cache_hit,
            "cache_type": cache_type,
            "error_message": error_message,
            "error_type": "resource_not_found" if not success else None,
        }

        await self._queue_event(event)

        # Console logging for visibility
        token_id = event.get("token_id", "unknown")
        cache_str = " [cached]" if cache_hit else ""
        if success:
            logger.info(
                "📊 Resource: %s | Token: %s | %.0fms%s",
                resource_uri,
                token_id,
                response_time_ms,
                cache_str,
            )
        else:
            logger.warning(
                "📊 Resource: %s | Token: %s | Error: %s", resource_uri, token_id, error_message
            )

        # Error patterns are tracked in mcp_events table

    # ========================================================================
    # Pattern Tracking (All tracking in mcp_events table)
    # ========================================================================
    # Note: Query patterns and error patterns are tracked in mcp_events table.
    # Use SQL queries on mcp_events to analyze popular queries and error patterns.

    # ========================================================================
    # Context Management
    # ========================================================================

    @staticmethod
    def _extract_token_id(token: str) -> str | None:
        """
        Extract token ID from token string.

        Supports both formats:
        1. API Token: idt:TKN-XXXX-XXXX:actual_token → Returns TKN-XXXX-XXXX
        2. JWT Token: header.payload.signature → Returns USR-XXXX-XXXX (from JWT claims)

        Args:
            token: The authentication token (with or without Bearer prefix)

        Returns:
            Token identifier (TKN-XXXX-XXXX or USR-XXXX-XXXX) or None if not found
        """
        # Remove "Bearer " prefix if present for parsing
        token_value = token.replace("Bearer ", "").strip()

        # Use parse_token_id from token_validator which handles both JWT and API tokens
        return parse_token_id(token_value)

    @staticmethod
    def set_context(
        token: str | None = None,
        endpoint: str | None = None,
        client_info: str | None = None,
        session_id: str | None = None,
        client_ip: str | None = None,
    ):
        """
        Set context variables for analytics tracking.

        Args:
            token: API token (will be hashed for storage)
            endpoint: API endpoint
            client_info: Client information (e.g., "Cursor", "Claude Desktop")
            session_id: Session identifier
            client_ip: Client IP address (IPv4 or IPv6)
        """
        if session_id:
            _current_session_id.set(session_id)
        if token:
            # Extract token ID (e.g., TKN-XXXX-XXXX from idt:TKN-XXXX-XXXX:SECRET)
            token_id = AnalyticsLogger._extract_token_id(token)
            _current_token_id.set(token_id)
        if endpoint:
            _current_api_endpoint.set(endpoint)
        if client_info:
            _current_client_info.set(client_info)
        if client_ip:
            _current_client_ip.set(client_ip)


# ============================================================================
# Global Analytics Logger Instance
# ============================================================================
_analytics_logger: AnalyticsLogger | None = None


def get_analytics_logger() -> AnalyticsLogger | None:
    """Get global analytics logger instance (returns None if not initialized)."""
    return _analytics_logger


async def initialize_analytics(database_url: str | None = None, **kwargs) -> AnalyticsLogger:
    """
    Initialize global analytics logger.

    Args:
        database_url: PostgreSQL connection string
        **kwargs: Additional arguments for AnalyticsLogger

    Returns:
        Initialized AnalyticsLogger instance
    """
    global _analytics_logger
    _analytics_logger = AnalyticsLogger(database_url=database_url, **kwargs)
    await _analytics_logger.initialize()
    return _analytics_logger
