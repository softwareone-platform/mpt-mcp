# Architecture

This document describes how the MCP server is structured. Shared Python rules live in [python-coding.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/python-coding.md); this file covers repository-specific design only.

## Transports

The package serves one FastMCP server, built by `create_mcp_server()` ([`server.py`](../mpt_mcp/server.py)), over two transports:

| Transport | Entry point | Tenancy | Credentials |
|---|---|---|---|
| HTTP (streamable) | `python -m mpt_mcp.runtime.runner` ([`runtime/runner.py`](../mpt_mcp/runtime/runner.py)) | Multi-tenant | Each request sends `X-MPT-Authorization` and, optionally, `X-MPT-Endpoint` |
| stdio | `python -m mpt_mcp.runtime.stdio` ([`runtime/stdio.py`](../mpt_mcp/runtime/stdio.py)) | Single-tenant | `MARKETPLACE_API_TOKEN` and `MARKETPLACE_API_BASE_URL` from the environment |

Both transports serve the same tools, resources and prompts: `create_mcp_server(transport=...)` only changes the lifespans and middlewares. Both run `spec_lifespan` ([`tools/spec_store.py`](../mpt_mcp/tools/spec_store.py)), which only creates an empty store of OpenAPI specs and their disk cache, so it does not delay startup. Only the HTTP server records analytics and, in `documentation_lifespan` ([`documentation/lifespan.py`](../mpt_mcp/documentation/lifespan.py)), loads the documentation when it starts and registers each page as a resource, so clients can discover them. The stdio server runs `documentation_store_lifespan` instead, which creates an empty `DocumentationStore` that loads on the first documentation call, so a client that starts it does not wait for GitBook.

The [`runtime/`](../mpt_mcp/runtime) package starts the transports:

| Module | Responsibility |
|---|---|
| [`runner.py`](../mpt_mcp/runtime/runner.py) | HTTP entry point: startup banner, migrations and uvicorn |
| [`main.py`](../mpt_mcp/runtime/main.py) | `app`, the ASGI app uvicorn imports (`mpt_mcp.runtime.main:app`) in each worker and on each reload |
| [`http.py`](../mpt_mcp/runtime/http.py) | `create_http_app()`: the MCP endpoint, the health check, the path rewrite and the not found hint |
| [`stdio.py`](../mpt_mcp/runtime/stdio.py) | stdio entry point |
| [`migrations.py`](../mpt_mcp/runtime/migrations.py) | Analytics database migrations at HTTP startup |
| [`middleware.py`](../mpt_mcp/runtime/middleware.py) | `RequestContextMiddleware`, the MCP middleware of both transports that sets the log context |
| [`logging.py`](../mpt_mcp/runtime/logging.py) | Logging configuration of both transports |

## HTTP Request Flow

`create_http_app()` ([`runtime/http.py`](../mpt_mcp/runtime/http.py)) builds the app without side effects; the server lifespans run when uvicorn starts it:

1. `MCPPathMiddleware` (ASGI) rewrites `POST /` and `POST /mcp/` to `POST /mcp`, for proxies that strip or add the path. `GET /` and `GET /health` are FastMCP custom routes that return the health status. Unknown paths return a JSON 404 with a hint.
2. FastMCP's streamable HTTP app (`mcp.http_app(stateless_http=True)`) handles `/mcp`. The server is stateless: there are no server-side MCP sessions, so any instance behind a load balancer can serve any request.
3. FastMCP middlewares run for every MCP request, in this order:
   - `RequestContextMiddleware` ([`runtime/middleware.py`](../mpt_mcp/runtime/middleware.py)) sets the caller's user ID and the `session_id` query parameter as the log prefix, and logs caller activity (at most every 30 seconds per caller).
   - `AnalyticsMiddleware` ([`analytics/middleware.py`](../mpt_mcp/analytics/middleware.py)) sets the caller's analytics context (token ID, endpoint, client, IP and session) for the request and records one event per tool call, prompt get and resource read.
4. Tools and the OpenAPI resource receive a `CallContext` with `Depends(get_call_context)` ([`auth/call_context.py`](../mpt_mcp/auth/call_context.py)), built from the `X-MPT-*` headers. `CallContext.create_api_client()` validates the token with the server's `TokenValidator`, which `token_lifespan` creates for both transports, and returns an `APIClient` for the caller's endpoint. The Marketplace tools receive that client and the endpoint's OpenAPI spec through the dependencies of [`tools/dependencies.py`](../mpt_mcp/tools/dependencies.py) (`get_api_client`, `get_marketplace_spec`), which FastMCP resolves once per call. `get_marketplace_spec` reads the spec from the `MarketplaceSpecStore` of the lifespan context, which loads each endpoint's spec on its first call, one load at a time. A spec that cannot be loaded raises `OpenAPISpecFetchError` in [`marketplace/endpoint_registry.py`](../mpt_mcp/marketplace/endpoint_registry.py), which the dependency turns into a tool error, and it is not kept, so the next call retries it.

The stdio server has no HTTP request: `get_call_context()` builds the `CallContext` from `MARKETPLACE_API_BASE_URL` and `MARKETPLACE_API_TOKEN`, and the tools run the same way.

Tools report failures by raising `ToolError`, built with `tool_error()` ([`tools/results.py`](../mpt_mcp/tools/results.py)): MCP clients receive an error result (`isError: true`) whose text is the message followed by its hints (`hint`, `did_you_mean`, `example`…) as JSON. FastMCP never masks `ToolError` messages. Errors are not detected from the response payload, because some Marketplace resources, such as orders, have an `error` field of their own. The `api://openapi.json` ([`resources.py`](../mpt_mcp/resources.py)) and `docs://` ([`documentation/server.py`](../mpt_mcp/documentation/server.py)) resources report failures the same way, with `ResourceError`.

Every tool returns a Pydantic model from [`tools/responses/`](../mpt_mcp/tools/responses), and FastMCP publishes it as the tool's `outputSchema`, with a description per field, and sends the result as structured content. The models keep keys they do not declare (`extra="allow"`), so a response never loses data the API returns: `QueryResponse` only types the `$meta` and `data` envelope, and the fields of a single item stay as they come. Optional fields without a value are left out of the response. Resources that return a plain value instead of an object are sent as `{"result": ...}`.

Tool results are kept under `CHARACTER_LIMIT` (25,000 characters) ([`tools/results.py`](../mpt_mcp/tools/results.py)). Every result stays in the model's context for the rest of the conversation, and some MCP clients reject long ones, so the limit leaves room for several results in any client. It is still high enough for a page of dozens of compact items, for most documentation pages and for the schema of the largest resources. The results that can be longer are shortened, and say so:

- `marketplace_query` cuts a page to the items that fit and reports it in `$meta.truncated`, with a limit that fits; `$meta.pagination.next_offset` continues it.
- `marketplace_docs_read` returns long pages in parts, cut at a line break, with the `next_offset` of the next part.
- `marketplace_resources` lists only resource names (or, for one category, names and summaries) when the full list does not fit, and adds a `note`.

Every tool declares a `title` and MCP annotations: all are read-only (`readOnlyHint`) except `marketplace_refresh_cache`, and `openWorldHint` marks the tools that reach the Marketplace API or GitBook. The server sends `instructions` ([`server.py`](../mpt_mcp/server.py)) that describe the order to use the tools in and the RQL operators. Common questions are prompts ([`prompts.py`](../mpt_mcp/prompts.py)), which the user picks in the client, rather than a tool: each one fills in a `marketplace_query` call from its arguments for the model to run. The examples the model needs for a resource come from `marketplace_resource_info`, generated from the OpenAPI spec.

## Modules

| Module | Responsibility |
|---|---|
| [`auth/call_context.py`](../mpt_mcp/auth/call_context.py) | Caller credentials from the `X-MPT-*` headers (HTTP) or the environment (stdio); token validation before creating the API client |
| [`auth/token_validator.py`](../mpt_mcp/auth/token_validator.py) | `TokenValidator`: API token (`idt:TKN-…`) and JWT validation against the Marketplace API, with its lifespan and dependency. `tokens.py` parses and normalizes tokens, `token_cache.py` holds the validation cache (10 minutes) and `jwt_verifier.py` verifies JWTs with a JWKS cache (1 hour) |
| [`marketplace/api_client.py`](../mpt_mcp/marketplace/api_client.py) | Authenticated Marketplace API client; RQL is sent as the raw query string; endpoints are normalized to `scheme://host[:port]` |
| [`marketplace/endpoint_registry.py`](../mpt_mcp/marketplace/endpoint_registry.py) | Fetches the OpenAPI spec of an endpoint, with its disk cache (`.cache/`, 24 hours) and the production fallback, and builds the registry of its GET resources |
| [`marketplace/cache_manager.py`](../mpt_mcp/marketplace/cache_manager.py) | Disk cache for fetched JSON documents (OpenAPI specs) |
| [`marketplace/openapi_parser.py`](../mpt_mcp/marketplace/openapi_parser.py) | Extracts the GET endpoints of an OpenAPI spec |
| [`marketplace/schemas.py`](../mpt_mcp/marketplace/schemas.py) | `OpenAPISpec`: the operations of a path, the 200 JSON response schema of an operation, the schema of one item of a list response, and `$ref` and `allOf` resolution |
| [`marketplace/audit_fields.py`](../mpt_mcp/marketplace/audit_fields.py) | Detects the audit events of each resource in the spec, and builds the pattern that lets queries that filter or sort by them add those fields to `select` (`+audit.created.at`) |
| [`server.py`](../mpt_mcp/server.py) | Creates the server for a transport: instructions, middlewares, the spec lifespan, documentation and analytics lifespans (HTTP), tools, resources, prompts and debug tool visibility |
| [`tools/`](../mpt_mcp/tools) | The Marketplace tools. Each module registers its tools on a `LocalProvider` that `create_mcp_server()` adds: `query/` (`marketplace_query`) and `resources/` (resource list, info, schema and audit events) keep the tools in `tool.py` and their logic in the other modules; `debug.py` holds the `DEBUG_TAG` tools. `spec.py` holds `MarketplaceSpec`, the caller's endpoint spec with its resource and schema lookups and audit events, and `spec_store.py` the store of the endpoints' specs and its lifespan, which `dependencies.py` injects with the API client; `results.py` holds the result size limit and `tool_error()`, `responses/` the response models, one module per tool group with the public ones exported from its `__init__.py`, and `annotations.py` the MCP annotations |
| [`resources.py`](../mpt_mcp/resources.py), [`prompts.py`](../mpt_mcp/prompts.py) | The OpenAPI resource and the prompts, each on its `LocalProvider` (`openapi_resources`, `marketplace_prompts`) |
| [`documentation/`](../mpt_mcp/documentation) | Marketplace documentation: `server.py` holds the `marketplace_docs_*` tools and the `docs://` resource on `documentation_provider`; `gitbook.py` and `cache.py` are the GitBook client and the cache; `store.py` holds the `DocumentationStore` that loads the cache once per server, which the tools receive with `Depends(get_documentation_cache)`, and `lifespan.py` the lifespans that create it, `documentation_lifespan` loading it at HTTP startup |
| [`runtime/`](../mpt_mcp/runtime) | Transport entry points, HTTP app, migrations, request log context and logging configuration (see [Transports](#transports)) |
| [`analytics/`](../mpt_mcp/analytics) | Analytics lifespan, middleware, buffered logger and `mcp_events` table |
| [`config.py`](../mpt_mcp/config.py) | Configuration read from environment variables (and `.env` through `python-dotenv`) |

## Logging

All modules log through `logging.getLogger(__name__)`. Both entry points call `configure_logging()` ([`runtime/logging.py`](../mpt_mcp/runtime/logging.py)), which sends every record to stderr (stdout carries the stdio JSON-RPC stream) with this format, keeps FastMCP and the MCP SDK at `WARNING` and leaves the requests to `/mcp` and `/health` out of the uvicorn access log:

```text
INFO [mpt_mcp.runtime.middleware] [sess:abcdef12|user:TKN-1111-2222] TKN-1111-2222 @ api.s1.show [token] (active)
```

`RequestContextFilter` adds the `[sess|user]` prefix from the context vars that `RequestContextMiddleware` sets. The level is `DEBUG` when `DEBUG=true`, otherwise `INFO`.

## Analytics

Analytics is optional and only runs in the HTTP server when `ANALYTICS_DATABASE_URL` is set:

- `analytics_lifespan` ([`analytics/lifespan.py`](../mpt_mcp/analytics/lifespan.py)) creates the server's `AnalyticsLogger` inside its event loop, keeps it in the lifespan context and closes it on shutdown, which flushes pending events. `AnalyticsMiddleware` reads it from there, and `marketplace_query` receives it as `Depends(get_analytics_logger)`, which gives `None` on the stdio server.
- `AnalyticsLogger` ([`analytics/logger.py`](../mpt_mcp/analytics/logger.py)) records typed events ([`analytics/events.py`](../mpt_mcp/analytics/events.py): `ToolCallEvent`, `PromptGetEvent`, `ResourceReadEvent`, `ApiQueryEvent`, whose fields are `mcp_events` columns) with the caller's context, logs each one to the console, and inserts them in batches (every 5 seconds or 50 events) into `mcp_events`.
- Tool calls, prompt gets and resource reads are recorded by `AnalyticsMiddleware`; Marketplace API queries are recorded by `MarketplaceRequest` ([`tools/query/request.py`](../mpt_mcp/tools/query/request.py)) with their RQL, pagination and status code.

The schema is managed with Alembic, see [migrations.md](migrations.md).

## Debug Tools

The tools `marketplace_cache_info`, `marketplace_refresh_cache` and `marketplace_resources_info` are tagged `debug` and disabled with FastMCP visibility unless `DEBUG=true`; when disabled they are neither listed nor callable.

## Design Decisions

- **Stateless HTTP**: no MCP sessions, so horizontal scaling and redeploys do not break clients. Per-process caches (OpenAPI specs, token validations, documentation) are rebuilt on demand.
- **Credentials per request**: the HTTP server never stores client tokens; it validates the caller's token on each tool call (cached by a hash of token and endpoint).
- **Dependency injection over context vars for credentials**: tools receive `CallContext`, the API client or the endpoint spec explicitly through `Depends`, which keeps them testable with plain arguments.
- **Process state in the lifespan over module globals**: the OpenAPI specs, with their disk cache, live in the `MarketplaceSpecStore` that `spec_lifespan` creates for each server, the documentation in the `DocumentationStore` of the documentation lifespans, and the token validation and JWKS caches in the `TokenValidator` of `token_lifespan`, read through `Depends`, so each server, and each test server, has its own. The specs still load on each endpoint's first call, since the HTTP server only learns the caller's endpoint from the request.
- **A `LocalProvider` per module over `@mcp.tool` and mounted servers**: the server is created in a factory, so each module declares its tools, resources or prompts on its own provider (`@resource_tools.tool(...)`, `@marketplace_prompts.prompt(...)`) and the factory only adds the providers; no module needs a server instance at import time, and a new tool, resource or prompt does not touch `server.py`.

## Design Rules

Where new code goes and what each layer may do:

- Both transports serve the server that [`mpt_mcp/server.py`](../mpt_mcp/server.py) creates: add Marketplace tools to the [`tools/`](../mpt_mcp/tools) module of their domain, with their logic, Marketplace resources and prompts to `resources.py` and `prompts.py`, and documentation ones to [`documentation/server.py`](../mpt_mcp/documentation/server.py), never to the [`runtime/`](../mpt_mcp/runtime) entry points, which only start the transports.
- Tools must get the caller's credentials with `call_context: CallContext = Depends(get_call_context)`, or the API client and spec with `Depends(get_api_client)` and `Depends(get_marketplace_spec)`, not by reading request headers or `config`.
- Tool arguments with a fixed range must declare it with `Annotated[..., Field(...)]`, so the input schema shows it and FastMCP rejects other values before the tool runs.
- Cross-cutting request behaviour (log context, analytics) must live in FastMCP middlewares, not in tools.
- Development-only tools must be tagged with `DEBUG_TAG`.
- Tool docstrings are the descriptions MCP clients send to the model; treat changes to them as user-facing changes.
- Analytics schema changes must go through an Alembic migration, see [migrations.md](migrations.md).
