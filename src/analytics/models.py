from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

# ============================================================================
# Main Events Table (all MCP activity)
# ============================================================================
mcp_events = Table(
    "mcp_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    # Timing
    Column("timestamp", DateTime, nullable=False, server_default=func.now()),
    Column("response_time_ms", Integer),
    # User/Environment (Privacy-Safe)
    Column("token_id", String(20)),  # TKN-XXXX-XXXX or USR-XXXX-XXXX
    Column("api_endpoint", String(100)),  # api.s1.show, etc.
    Column("session_id", String(100)),
    # Event Classification
    Column("event_type", String(50), nullable=False),  # tool_call, resource_read, api_query, error
    Column("server_type", String(20)),  # http, stdio
    # MCP Tool Details
    Column("tool_name", String(100)),
    Column("resource_uri", Text),
    # API Query Details
    Column("api_resource", String(200)),  # catalog.products
    Column("api_path", Text),  # /public/v1/catalog/products
    Column("api_method", String(10)),  # GET, POST, etc.
    Column("api_status_code", Integer),
    Column("api_response_time_ms", Integer),
    Column("result_count", Integer),
    # Query Parameters
    Column("rql_filter", Text),
    Column("limit_value", Integer),
    Column("offset_value", Integer),
    Column("order_by", String(200)),
    Column("select_fields", Text),
    # Performance Tracking
    Column("cache_hit", Boolean),
    Column("cache_type", String(50)),  # documentation, token, openapi
    # Error Tracking
    Column("error_type", String(50)),  # validation, api_error, auth_error, internal
    Column("error_message", Text),
    Column("error_details", JSONB),
    # Metadata
    Column("server_version", String(20)),
    Column("client_info", Text),  # MCP client (Cursor, Claude Desktop, etc.)
    Column("client_ip", String(45)),  # IPv4 or IPv6 address (max 45 chars for IPv6)
)

# Indexes for performance
Index("idx_events_timestamp", mcp_events.c.timestamp.desc())
Index("idx_events_token_id", mcp_events.c.token_id)
Index("idx_events_tool_name", mcp_events.c.tool_name)
Index("idx_events_api_resource", mcp_events.c.api_resource)
Index("idx_events_event_type", mcp_events.c.event_type)
Index("idx_events_error_type", mcp_events.c.error_type, postgresql_where=mcp_events.c.error_type.isnot(None))
Index("idx_events_date_token", func.date(mcp_events.c.timestamp), mcp_events.c.token_id)
Index("idx_events_date_tool", func.date(mcp_events.c.timestamp), mcp_events.c.tool_name)
Index("idx_events_client_ip", mcp_events.c.client_ip)


# ============================================================================
# Database Management Class
# ============================================================================
class AnalyticsDB:
    """Helper class for analytics database operations."""

    @staticmethod
    def get_all_tables():
        """Return all table definitions."""
        return [mcp_events]

    @staticmethod
    def get_metadata():
        """Return SQLAlchemy metadata."""
        return metadata
