# Version Migrations

This document lists the changes between versions that require action from users of the server or from developers of this repository. Analytics database migrations are described in [migrations.md](migrations.md).

Add an entry to the `Unreleased` section in the same change that introduces a breaking change.

## Unreleased

- The package is renamed from `src` to `mpt_mcp`. Local MCP client configurations must run `python -m mpt_mcp.server_stdio` instead of `python -m src.server_stdio`, and the HTTP server runs with `python -m mpt_mcp.server`. See [`examples/`](../examples/README.md).
- The stdio tools `marketplace_cache_info` and `marketplace_refresh_cache` are only available when `DEBUG=true`.
- The `SSE_ENABLED`, `TOOL_INCLUDE_PATTERNS` and `TOOL_EXCLUDE_PATTERNS` environment variables are no longer read. They had no effect and can be removed from `.env` files.
