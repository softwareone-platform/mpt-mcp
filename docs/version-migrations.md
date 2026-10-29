# Version Migrations

This document lists the changes between versions that require action from users of the server or from developers of this repository. Analytics database migrations are described in [migrations.md](migrations.md).

Add an entry to the `Unreleased` section in the same change that introduces a breaking change.

## Unreleased

- The package is renamed from `src` to `mpt_mcp`. Local MCP client configurations must run `python -m mpt_mcp.server_stdio` instead of `python -m src.server_stdio`, and the HTTP server runs with `python -m mpt_mcp.server`. See [`examples/`](../examples/README.md).
- The HTTP and stdio servers serve the same tools and resources. The stdio server gains the documentation tools and the `api://openapi.json` and `docs://` resources, and validates `MARKETPLACE_API_TOKEN` before its first query. The debug tools `marketplace_cache_info`, `marketplace_refresh_cache` and `marketplace_resources_info` are only available when `DEBUG=true` in both servers, so the HTTP server no longer lists `marketplace_resources_info` in production.
- `marketplace_query` no longer accepts `page`: the Marketplace API only paginates with `limit` and `offset`, and it rejected the `page` parameter with 400 Bad Request. Use `offset` instead (`offset = (page - 1) * limit`).
- The stdio server loads the OpenAPI spec of `MARKETPLACE_API_BASE_URL` (`{endpoint}/public/v1/openapi.json`), as the HTTP server does for its caller's endpoint. `OPENAPI_SPEC_URL` is no longer read: remove it from `.env` files and MCP client configurations.
- The `SSE_ENABLED`, `SSE_HOST`, `SSE_PORT`, `SSE_CORS_ORIGINS`, `TOOL_INCLUDE_PATTERNS` and `TOOL_EXCLUDE_PATTERNS` environment variables are no longer read. They had no effect and can be removed from `.env` files.
