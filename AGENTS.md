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

- [`mpt_mcp/runtime/`](mpt_mcp/runtime): transport entry points (`runner.py` for HTTP, `stdio.py`), HTTP app and health check, migrations, request log context and logging setup
- [`mpt_mcp/tools/`](mpt_mcp/tools): the Marketplace tools with their logic (`query.py`, `resources.py`, `debug.py`), result size limits and errors (`results.py`), response models (`responses.py`) and annotations
- [`mpt_mcp/server_resources.py`](mpt_mcp/server_resources.py) and [`mpt_mcp/server_prompts.py`](mpt_mcp/server_prompts.py): the OpenAPI resource and the prompts of both transports
- [`mpt_mcp/mcp_server.py`](mpt_mcp/mcp_server.py): the MCP server both transports serve, with its middlewares and debug tool visibility
- [`mpt_mcp/auth/`](mpt_mcp/auth): per-request credentials injected with FastMCP dependencies (`call_context.py`) and token validation (`token_validator.py`)
- [`mpt_mcp/analytics/`](mpt_mcp/analytics): analytics middleware, lifespan, logger and table model
- [`mpt_mcp/marketplace/`](mpt_mcp/marketplace): Marketplace API client, OpenAPI-based endpoint discovery and its disk cache, OpenAPI parsing and audit field detection
- [`mpt_mcp/documentation/`](mpt_mcp/documentation): documentation server (its tools and the `docs://` resource, mounted into the MCP server), GitBook client, cache and startup loading
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
