import logging
import sys
import warnings
from contextvars import ContextVar

# Loggers that follow the configured level; third-party libraries stay at INFO, so DEBUG never
# dumps their internals (httpcore and hpack log the request headers, Authorization included)
APP_LOGGERS = ("__main__", "mpt_mcp")
# Third-party loggers that only log protocol details at INFO
QUIET_LOGGERS = ("fastmcp", "mcp")
# Requests every MCP client and health check makes: logging each one hides the other access logs
UNLOGGED_ACCESS_PATHS = frozenset(("/mcp", "/health", "GET /health", "POST /mcp"))
ACCESS_LOG_PATH_ARG = 2
LOG_FORMAT = "%(levelname)s [%(name)s] %(request_context)s%(message)s"
SESSION_ID_LOG_LENGTH = 8
# Caller of the current MCP request: set by RequestContextMiddleware, read by RequestContextFilter
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


class RequestContextFilter(logging.Filter):
    """Add the caller's session and user ID of the current MCP request to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Set record.request_context to "[sess:...|user:...] ", or "" outside a request."""
        context_parts = []
        session_id = current_session_id.get()
        if session_id:
            short_session_id = session_id[:SESSION_ID_LOG_LENGTH]
            context_parts.append(f"sess:{short_session_id}")

        user_id = current_user_id.get()
        if user_id:
            context_parts.append(f"user:{user_id}")

        request_context = "|".join(context_parts)
        record.request_context = f"[{request_context}] " if context_parts else ""
        return True


class AccessLogFilter(logging.Filter):
    """Drop the uvicorn access logs of the MCP endpoint and the health check."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep the record unless its request path is one of UNLOGGED_ACCESS_PATHS."""
        if isinstance(record.args, tuple) and len(record.args) > ACCESS_LOG_PATH_ARG:
            return str(record.args[ACCESS_LOG_PATH_ARG]) not in UNLOGGED_ACCESS_PATHS

        return True


def configure_logging(level: int = logging.INFO) -> None:
    """
    Send all logs to stderr with the request context prefix.

    stderr keeps stdout free for the JSON-RPC stream of the stdio transport. FastMCP and the MCP
    SDK only log warnings, and uvicorn does not log the requests to /mcp and /health.

    Args:
        level: Log level of the application loggers
    """
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.addFilter(RequestContextFilter())
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.basicConfig(level=logging.INFO, handlers=[stream_handler], force=True)
    for logger_name in APP_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)
    for logger_name in QUIET_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").addFilter(AccessLogFilter())
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
    warnings.filterwarnings(
        "ignore", category=DeprecationWarning, message=".*websockets.*deprecated.*"
    )
