# Architecture

This document describes how the MCP server is structured. Shared Python rules live in [python-coding.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/python-coding.md); this file covers repository-specific design only.

## Transports

The package serves one FastMCP server, built by `create_mcp_server()` ([`mcp_server.py`](../mpt_mcp/mcp_server.py)), over two transports:

| Transport | Entry point | Tenancy | Credentials |
|---|---|---|---|
| HTTP (streamable) | `python -m mpt_mcp.server` ([`server.py`](../mpt_mcp/server.py)) | Multi-tenant | Each request sends `X-MPT-Authorization` and, optionally, `X-MPT-Endpoint` |
| stdio | `python -m mpt_mcp.server_stdio` ([`server_stdio.py`](../mpt_mcp/server_stdio.py)) | Single-tenant | `MARKETPLACE_API_TOKEN` and `MARKETPLACE_API_BASE_URL` from the environment |

Both transports serve the same tools and resources. Only the HTTP server records analytics and registers each documentation page as a resource at startup, so clients can discover them.

## HTTP Request Flow

The HTTP app is built once at import time (`server.app`, which uvicorn loads as `mpt_mcp.server:app`):

1. `HealthCheckMiddleware` (ASGI) answers `GET /` and `GET /health`, and rewrites `POST /` and `POST /mcp/` to `POST /mcp`. Unknown paths return a JSON 404 with a hint.
2. FastMCP's streamable HTTP app (`mcp.http_app(stateless_http=True)`) handles `/mcp`. The server is stateless: there are no server-side MCP sessions, so any instance behind a load balancer can serve any request.
3. FastMCP middlewares run for every MCP request, in this order:
   - `RequestContextMiddleware` ([`server_middleware.py`](../mpt_mcp/server_middleware.py)) sets the caller's user ID and the `session_id` query parameter as the log prefix, and logs caller activity (at most every 30 seconds per caller).
   - `AnalyticsMiddleware` ([`analytics/middleware.py`](../mpt_mcp/analytics/middleware.py)) sets the analytics context and records one event per tool call and per resource read.
4. Tools and the OpenAPI resource receive a `CallContext` with `Depends(get_call_context)` ([`call_context.py`](../mpt_mcp/call_context.py)), built from the `X-MPT-*` headers. `CallContext.create_api_client()` validates the token and returns an `APIClient` for the caller's endpoint.

The stdio server has no HTTP request: `get_call_context()` builds the `CallContext` from `MARKETPLACE_API_BASE_URL` and `MARKETPLACE_API_TOKEN`, and the tools run the same way.

Tools report failures by raising `ToolError`, built with `tool_error()` ([`mcp_tools.py`](../mpt_mcp/mcp_tools.py)): MCP clients receive an error result (`isError: true`) whose text is the message followed by its hints (`hint`, `did_you_mean`, `example`…) as JSON. FastMCP never masks `ToolError` messages. Errors are not detected from the response payload, because some Marketplace resources, such as orders, have an `error` field of their own.

Every tool returns a Pydantic model from [`tool_responses.py`](../mpt_mcp/tool_responses.py), and FastMCP publishes it as the tool's `outputSchema`, with a description per field, and sends the result as structured content. The models keep keys they do not declare (`extra="allow"`), so a response never loses data the API returns: `QueryResponse` only types the `$meta` and `data` envelope, and the fields of a single item stay as they come. Optional fields without a value are left out of the response. Resources that return a plain value instead of an object are sent as `{"result": ...}`.

Every tool declares a `title` and MCP annotations: all are read-only (`readOnlyHint`) except `marketplace_refresh_cache`, and `openWorldHint` marks the tools that reach the Marketplace API or GitBook. The server sends `instructions` ([`mcp_server.py`](../mpt_mcp/mcp_server.py)) that describe the order to use the tools in.

## Modules

| Module | Responsibility |
|---|---|
| [`call_context.py`](../mpt_mcp/call_context.py) | Caller credentials from the `X-MPT-*` headers (HTTP) or the environment (stdio); token validation before creating the API client |
| [`token_validator.py`](../mpt_mcp/token_validator.py) | API token (`idt:TKN-…`) and JWT validation against the Marketplace API, with an in-memory validation cache (10 minutes) and a JWKS cache (1 hour) |
| [`api_client.py`](../mpt_mcp/api_client.py) | Authenticated Marketplace API client; RQL is sent as the raw query string; endpoints are normalized to `scheme://host[:port]` |
| [`endpoint_registry.py`](../mpt_mcp/endpoint_registry.py) | Per-endpoint registry of GET resources built from the OpenAPI spec, cached in memory and on disk (`.cache/`, 24 hours); a spec that fails to load is not cached, so the next call retries it |
| [`openapi_parser.py`](../mpt_mcp/openapi_parser.py) | Extracts the GET endpoints of an OpenAPI spec |
| [`audit_fields.py`](../mpt_mcp/audit_fields.py) | Detects audit fields per resource so queries that filter or sort by them add `select=audit` |
| [`mcp_tools.py`](../mpt_mcp/mcp_tools.py) | Tool logic shared by both servers: query execution, select sanitization, resource info and schemas |
| [`query_templates.py`](../mpt_mcp/query_templates.py) | Example queries returned by `marketplace_quick_queries` |
| [`mcp_server.py`](../mpt_mcp/mcp_server.py) | Creates the server: middlewares, analytics lifespan (HTTP), tools, resources and debug tool visibility |
| [`server_tools.py`](../mpt_mcp/server_tools.py), [`server_resources.py`](../mpt_mcp/server_resources.py) | Tool and resource functions and their registration |
| [`tool_responses.py`](../mpt_mcp/tool_responses.py) | One Pydantic response model per tool, with the nested models of its fields, from which FastMCP builds the tool's output schema |
| [`server_docs.py`](../mpt_mcp/server_docs.py), [`documentation_cache.py`](../mpt_mcp/documentation_cache.py), [`gitbook_client.py`](../mpt_mcp/gitbook_client.py) | GitBook documentation cache, created once per process |
| [`server_middleware.py`](../mpt_mcp/server_middleware.py), [`log_config.py`](../mpt_mcp/log_config.py) | Request log context and logging configuration |
| [`analytics/`](../mpt_mcp/analytics) | Analytics lifespan, middleware, buffered logger and `mcp_events` table |
| [`cache_manager.py`](../mpt_mcp/cache_manager.py) | Disk cache for fetched JSON documents (OpenAPI specs) |
| [`config.py`](../mpt_mcp/config.py) | Configuration read from environment variables (and `.env` through `python-dotenv`) |

## Logging

All modules log through `logging.getLogger(__name__)`. Both entry points call `configure_logging()` ([`log_config.py`](../mpt_mcp/log_config.py)) once, which sends every record to stderr (stdout carries the stdio JSON-RPC stream) with this format:

```text
INFO [mpt_mcp.server_middleware] [sess:abcdef12|user:TKN-1111-2222] TKN-1111-2222 @ api.s1.show [token] (active)
```

`RequestContextFilter` adds the `[sess|user]` prefix from the context vars that `RequestContextMiddleware` sets. The level is `DEBUG` when `DEBUG=true`, otherwise `INFO`.

## Analytics

Analytics is optional and only runs in the HTTP server when `ANALYTICS_DATABASE_URL` is set:

- `analytics_lifespan` ([`analytics/lifespan.py`](../mpt_mcp/analytics/lifespan.py)) creates the logger inside the server's event loop and closes it on shutdown, which flushes pending events.
- `AnalyticsLogger` ([`analytics/logger.py`](../mpt_mcp/analytics/logger.py)) buffers events and inserts them in batches (every 5 seconds or 50 events) into `mcp_events`.
- Tool calls and resource reads are recorded by `AnalyticsMiddleware`; Marketplace API queries are recorded by `execute_marketplace_query` with their RQL, pagination and status code.

The schema is managed with Alembic, see [migrations.md](migrations.md).

## Debug Tools

The tools `marketplace_cache_info`, `marketplace_refresh_cache` and `marketplace_resources_info` are tagged `debug` and disabled with FastMCP visibility unless `DEBUG=true`; when disabled they are neither listed nor callable.

## Design Decisions

- **Stateless HTTP**: no MCP sessions, so horizontal scaling and redeploys do not break clients. Per-process caches (OpenAPI specs, token validations, documentation) are rebuilt on demand.
- **Credentials per request**: the HTTP server never stores client tokens; it validates the caller's token on each tool call (cached by a hash of token and endpoint).
- **Dependency injection over context vars for credentials**: tools receive `CallContext` explicitly through `Depends`, which keeps them testable with a plain `CallContext(...)` argument.
