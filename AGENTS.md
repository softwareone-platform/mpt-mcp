# AGENTS.md

Working protocol for any task in this repository:

1. Identify the task type and select only the local repository files that are relevant to that task.
2. Read only those relevant local files before making changes.
3. If any selected local file references shared standards or shared operational guidance that are relevant to the same task, read those shared documents too before proceeding.
4. Treat repository-local documents as repository-specific additions, restrictions, or overrides to shared guidance.
5. If a repository-local rule conflicts with a shared rule, the local repository rule takes precedence.

When applicable, read this repository in the following order:

1. [README.md](README.md) for the repository purpose, quick start, and documentation map.
2. [docs/architecture.md](docs/architecture.md) for the transports, request flow, and module responsibilities.
3. [docs/contributing.md](docs/contributing.md) for repository-specific workflow expectations and lint rules.
4. [docs/testing.md](docs/testing.md) before changing code or tests.
5. [docs/local-development.md](docs/local-development.md) when running the servers or connecting an MCP client.
6. [docs/usage.md](docs/usage.md) when a task changes a tool, its parameters or the connection headers.
7. [docs/external-integrations.md](docs/external-integrations.md) when a task touches the Marketplace API, GitBook, or the analytics database.
8. [docs/migrations.md](docs/migrations.md) when a task changes the analytics schema.
9. [docs/version-migrations.md](docs/version-migrations.md) when a task introduces a breaking change for users of the server.
10. [docs/deployment.md](docs/deployment.md) when a task touches the Cloud Run deployment or its configuration.
11. [docs/documentation.md](docs/documentation.md) when changing repository documentation.

Then inspect the code paths relevant to the task:

- [`mpt_mcp/server.py`](mpt_mcp/server.py): HTTP server, ASGI app, health check, startup and migrations
- [`mpt_mcp/server_tools.py`](mpt_mcp/server_tools.py) and [`mpt_mcp/server_resources.py`](mpt_mcp/server_resources.py): HTTP tools and resources
- [`mpt_mcp/server_stdio.py`](mpt_mcp/server_stdio.py): stdio server, its tools and the debug tools
- [`mpt_mcp/mcp_tools.py`](mpt_mcp/mcp_tools.py): tool logic shared by both servers (query, resources, schema)
- [`mpt_mcp/call_context.py`](mpt_mcp/call_context.py): per-request credentials injected with FastMCP dependencies
- [`mpt_mcp/server_middleware.py`](mpt_mcp/server_middleware.py) and [`mpt_mcp/log_config.py`](mpt_mcp/log_config.py): request log context and logging setup
- [`mpt_mcp/analytics/`](mpt_mcp/analytics): analytics middleware, lifespan, logger and table model
- [`mpt_mcp/api_client.py`](mpt_mcp/api_client.py), [`mpt_mcp/token_validator.py`](mpt_mcp/token_validator.py), [`mpt_mcp/endpoint_registry.py`](mpt_mcp/endpoint_registry.py): Marketplace API access, token validation and OpenAPI-based endpoint discovery
- [`mpt_mcp/documentation_cache.py`](mpt_mcp/documentation_cache.py), [`mpt_mcp/gitbook_client.py`](mpt_mcp/gitbook_client.py), [`mpt_mcp/server_docs.py`](mpt_mcp/server_docs.py): GitBook documentation cache
- [`mpt_mcp/config.py`](mpt_mcp/config.py): configuration read from environment variables
- [`tests/`](tests): pytest suite, one `test_<module>.py` per module
- [`make/`](make): canonical local commands

Operational guidance:

- Prefer documented `make` targets over ad hoc container commands.
- Treat Docker Compose as the default local execution model.
- Keep `README.md` short and navigational.
- Keep repository policy in `docs/` and keep `.github/copilot-instructions.md` thin.
- Tool docstrings are the tool descriptions MCP clients receive; treat changes to them as user-facing changes.
- Do not invent runtime or deployment behavior that is not implemented in the repository.
