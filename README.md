# SoftwareOne Marketplace MCP Server

`mpt-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server for the SoftwareOne Marketplace API, built on [FastMCP](https://gofastmcp.com). It exposes two transports:

- **HTTP (streamable)**: multi-tenant server where every client sends its own Marketplace API token in the `X-MPT-Authorization` header. Deployed at `https://mcp.platform.softwareone.com/mcp`.
- **stdio**: single-tenant server for local IDE integration, configured with `MARKETPLACE_API_TOKEN`.

## Documentation

Start here:

- [AGENTS.md](AGENTS.md): entry point for AI agents
- [docs/architecture.md](docs/architecture.md): transports, request flow, modules and design decisions
- [docs/usage.md](docs/usage.md): connecting to the server, the tools and query examples
- [docs/local-development.md](docs/local-development.md): local setup, running the servers and connecting MCP clients
- [docs/contributing.md](docs/contributing.md): repository-specific workflow and validation commands
- [docs/testing.md](docs/testing.md): test layout, commands and conventions
- [docs/external-integrations.md](docs/external-integrations.md): Marketplace API, GitBook and the analytics database
- [docs/migrations.md](docs/migrations.md): analytics database migrations with Alembic
- [docs/version-migrations.md](docs/version-migrations.md): breaking changes between versions and how to migrate
- [docs/deployment.md](docs/deployment.md): Cloud Run deployment
- [docs/documentation.md](docs/documentation.md): repository documentation rules
- [examples/README.md](examples/README.md): MCP client configuration examples

## Quick Start

Prerequisites:

- Docker with the `docker compose` plugin
- `make`

```bash
make build
make run
```

`make run` serves the HTTP server on `http://localhost:8080/mcp` (health check on `/health`). See [docs/local-development.md](docs/local-development.md) for the stdio server, the analytics database and client configuration.

## Repository Layout

- [`mpt_mcp/`](mpt_mcp): server package (HTTP and stdio servers, tools, Marketplace API client, analytics)
- [`tests/`](tests): pytest suite, one `test_<module>.py` per package module
- [`alembic/`](alembic): analytics database migrations
- [`examples/`](examples): MCP client configuration examples
- [`make/`](make): modular make targets
- [`docs/`](docs): repository documentation

## License

Licensed under the Apache License 2.0, see [LICENSE.md](LICENSE.md).
