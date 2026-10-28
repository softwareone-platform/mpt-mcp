# External Integrations

The server talks to three external systems. All of them are mocked in tests, see [testing.md](testing.md).

## SoftwareOne Marketplace API

- **OpenAPI spec**: fetched from `{endpoint}/public/v1/openapi.json` (falling back to the production spec) by [`endpoint_registry.py`](../mpt_mcp/endpoint_registry.py), and cached in memory per endpoint and on disk in `.cache/` for 24 hours. The GET endpoints become the resources that `marketplace_query` accepts (for example `catalog.products`).
- **Queries**: [`api_client.py`](../mpt_mcp/api_client.py) sends `GET` requests with `Authorization: Bearer <token>`. RQL is sent as the raw query string (`/catalog/products?eq(status,Published)&limit=10`), not as an `rql=` parameter.
- **Token validation** ([`token_validator.py`](../mpt_mcp/token_validator.py)):
  - API tokens (`idt:TKN-XXXX-XXXX:secret`) are checked with `GET /public/v1/accounts/api-tokens/{token_id}` and must be `Active`.
  - JWTs are verified with the issuer's JWKS (`JWT_JWKS_URL`, or `{iss}/.well-known/jwks.json`) using RS/ES algorithms only, then checked with `GET /public/v1/accounts/users/{user_id}`.
  - Results are cached for 10 minutes by a hash of token and endpoint; `X-MPT-Validate-Fresh: true` bypasses the cache.

The HTTP server is multi-tenant: the endpoint comes from `X-MPT-Endpoint` (default `SSE_DEFAULT_BASE_URL`), so a single deployment serves any Marketplace environment.

## GitBook

The HTTP server reads the Marketplace documentation from a GitBook space when `GITBOOK_API_KEY` and `GITBOOK_SPACE_ID` are set ([`gitbook_client.py`](../mpt_mcp/gitbook_client.py), [`documentation_cache.py`](../mpt_mcp/documentation_cache.py)):

- the page index is loaded at startup and refreshed every `GITBOOK_CACHE_REFRESH_HOURS` (24 by default); page content is fetched on first read
- requests are limited to `GITBOOK_MAX_CONCURRENT_REQUESTS` and retried on 429/503
- `GITBOOK_PUBLIC_URL` adds a public `browser_url` to each page

Without GitBook credentials the documentation tools return an error explaining how to enable them.

## Analytics Database (PostgreSQL)

When `ANALYTICS_DATABASE_URL` is set, the HTTP server stores usage events in the `mcp_events` table ([`analytics/models.py`](../mpt_mcp/analytics/models.py)): tool calls, resource reads and Marketplace API queries, with response times, errors, the caller's token ID (never the secret), client name and IP.

- Locally, `make run-analytics` starts the `analytics-db` container, see [local-development.md](local-development.md).
- In production the URL points to Cloud SQL, see [deployment.md](deployment.md).
- Schema changes go through Alembic, see [migrations.md](migrations.md).
