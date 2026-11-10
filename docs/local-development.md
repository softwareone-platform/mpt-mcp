# Local Development

This document covers running the servers locally and connecting MCP clients to them.

## Prerequisites

- Docker with the `docker compose` plugin
- `make`
- [uv](https://docs.astral.sh/uv/), only to run the servers without Docker

## Configuration

Configuration is read from environment variables; [`compose.yaml`](../compose.yaml) also loads an optional `.env` file. Copy [`.env.example`](../.env.example) to `.env` when you need any of these values:

| Variable | Used by | Purpose |
|---|---|---|
| `MARKETPLACE_API_TOKEN` | stdio | API token (`idt:TKN-XXXX-XXXX:secret`) of the single tenant |
| `MARKETPLACE_API_BASE_URL` | stdio | Marketplace API endpoint (default `https://api.platform.softwareone.com`) |
| `HTTP_DEFAULT_BASE_URL` | HTTP | Endpoint used when a client does not send `X-MPT-Endpoint` |
| `PORT` | HTTP | Listening port (default `8080`) |
| `DEBUG` | both | `true` enables debug logging, uvicorn reload and the debug tools |
| `GITBOOK_API_KEY`, `GITBOOK_SPACE_ID`, `GITBOOK_PUBLIC_URL` | both | Documentation tools and `docs://` resources; disabled when not set |
| `JWT_JWKS_URL`, `JWT_EXP_LEEWAY_SECONDS` | both | JWT verification; the JWKS URL is derived from the token's `iss` claim when not set |
| `ANALYTICS_DATABASE_URL` | HTTP | PostgreSQL URL (`postgresql+asyncpg://…`); analytics is disabled when not set |

`compose.yaml` sets `DEBUG=true` by default for local development; set `DEBUG=false` in `.env` to disable it.

## Running With Docker

| Command | What it runs |
|---|---|
| `make run` | HTTP server on `http://localhost:8080/mcp` |
| `make run-analytics` | HTTP server plus the `analytics-db` PostgreSQL container; migrations run on startup |
| `make run-stdio` | stdio server (needs `MARKETPLACE_API_TOKEN` in `.env`) |
| `make bash` | Shell in the app container |
| `make down` | Stop and remove the containers |

Compose profiles keep optional services out of the default stack: `stdio` for the stdio server and `analytics` for the database.

## Running Without Docker

```bash
uv sync
uv run python -m mpt_mcp.runtime.runner
MARKETPLACE_API_TOKEN=idt:TKN-XXXX-XXXX:secret uv run python -m mpt_mcp.runtime.stdio
```

## Connecting MCP Clients

Connect clients as described in [usage.md](usage.md), pointing the HTTP examples to `http://localhost:8080/mcp`. A `session_id` query parameter (`/mcp?session_id=…`) is added to the log prefix and to the analytics events.

## Testing With Claude Code

1. Start the HTTP server with `make run`.
2. In the folder you open in Claude Code, add the local server. Without `-s`, Claude Code stores it in your user configuration (`~/.claude.json`) for that folder only, so the token does not end up in a `.mcp.json` file:

   ```bash
   claude mcp add --transport http mpt-local http://localhost:8080/mcp --header "X-MPT-Authorization: idt:TKN-XXXX-XXXX:secret"
   ```

   Add `--header "X-MPT-Endpoint: https://api.s1.show"` to test against another Marketplace endpoint.
3. Start a new Claude Code session in that folder, or reconnect `mpt-local` with `/mcp`. Claude Code loads the tools when it connects, so reconnect after changing a tool's parameters or description too.

With `DEBUG=true`, the default in `compose.yaml`, uvicorn restarts the server whenever a file changes, and the restart disconnects Claude Code: reconnect with `/mcp`. `DEBUG=false` in `.env` avoids the restarts, but also hides the debug tools.

## Troubleshooting

- `curl http://localhost:8080/health` must return `{"status": "healthy", …}`.
- The MCP endpoint is `POST /mcp` without a trailing slash; `POST /mcp/` and `POST /` are rewritten to it, and other paths return a 404 with a hint.
- From another container, `localhost` is that container: use `http://host.docker.internal:8080/mcp`, or the service name when both containers share a Docker network.
- Server logs go to stderr; stdio clients such as Claude Desktop write them to their own log files (on macOS, `~/Library/Logs/Claude/mcp*.log`).
