import contextlib
import sys
from contextvars import ContextVar

# Ensure stderr is unbuffered so startup and request logs appear in Docker/console immediately
if hasattr(sys.stderr, "reconfigure"):
    with contextlib.suppress(Exception):
        sys.stderr.reconfigure(line_buffering=True)

# Log prefix of the current MCP request, set by RequestContextMiddleware
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)
current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def log(message: str, **kwargs):
    session_id = current_session_id.get()
    user_id = current_user_id.get()
    context_parts = []
    if session_id:
        context_parts.append(f"sess:{session_id[:8]}")
    if user_id:
        context_parts.append(f"user:{user_id}")
    prefix = f"[{('|'.join(context_parts))}] " if context_parts else ""
    print(f"{prefix}{message}", file=sys.stderr, flush=True, **kwargs)


def normalize_endpoint_url(endpoint: str) -> str:
    if not endpoint:
        return endpoint
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/public"):
        endpoint = endpoint[:-7]
    return endpoint
