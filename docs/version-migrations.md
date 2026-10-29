# Version Migrations

This document lists the changes between versions that require action from users of the server or from developers of this repository. Analytics database migrations are described in [migrations.md](migrations.md).

Add an entry to the `Unreleased` section in the same change that introduces a breaking change.

## Unreleased

- The package is renamed from `src` to `mpt_mcp`. Local MCP client configurations must run `python -m mpt_mcp.server_stdio` instead of `python -m src.server_stdio`, and the HTTP server runs with `python -m mpt_mcp.server`. See [`examples/`](../examples/README.md).
- The stdio tools `marketplace_cache_info` and `marketplace_refresh_cache` are only available when `DEBUG=true`.
- `marketplace_query` no longer accepts `page`: the Marketplace API only paginates with `limit` and `offset`, and it rejected the `page` parameter with 400 Bad Request. Use `offset` instead (`offset = (page - 1) * limit`).
- The stdio server loads the OpenAPI spec of `MARKETPLACE_API_BASE_URL` (`{endpoint}/public/v1/openapi.json`), as the HTTP server does for its caller's endpoint. `OPENAPI_SPEC_URL` is no longer read: remove it from `.env` files and MCP client configurations.
- The `SSE_ENABLED`, `TOOL_INCLUDE_PATTERNS` and `TOOL_EXCLUDE_PATTERNS` environment variables are no longer read. They had no effect and can be removed from `.env` files.
