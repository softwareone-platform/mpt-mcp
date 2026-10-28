# Documentation

This repository follows the shared documentation standard:

- [standards/documentation.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/documentation.md)

This file documents repository-specific documentation rules only.

## Repository Rules

- `README.md` must stay short and act as the main human entry point.
- `AGENTS.md` must stay operational and tell AI agents which files to read first.
- Topic-specific repository guidance must live in the matching file under [`docs/`](.).
- MCP client configuration examples live in [`examples/`](../examples/README.md), not in `README.md`.
- `.github/copilot-instructions.md` must remain a thin adapter that points back to [`AGENTS.md`](../AGENTS.md).
- When tools, configuration variables, make targets or the deployment change, update the corresponding document in the same change.

## Current Documentation Map

- [`README.md`](../README.md): human entry point, quick start and documentation map
- [`AGENTS.md`](../AGENTS.md): AI entry point and reading order
- [`architecture.md`](architecture.md): transports, request flow, modules and design decisions
- [`local-development.md`](local-development.md): configuration, running the servers and connecting clients
- [`usage.md`](usage.md): connecting to the server, the tools and query examples
- [`contributing.md`](contributing.md): repository-specific workflow and lint configuration
- [`testing.md`](testing.md): test layout, commands and conventions
- [`external-integrations.md`](external-integrations.md): Marketplace API, GitBook and the analytics database
- [`migrations.md`](migrations.md): analytics database migrations
- [`version-migrations.md`](version-migrations.md): breaking changes between versions
- [`deployment.md`](deployment.md): Cloud Run deployment

## Documentation Change Rule

When documentation changes, prefer updating the smallest relevant document instead of creating overlapping summary files.
