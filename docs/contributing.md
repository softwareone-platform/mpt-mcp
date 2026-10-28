# Contributing

This document captures repository-specific contribution guidance. Shared engineering rules live in `mpt-extension-skills` and are not duplicated here:

- [documentation.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/documentation.md)
- [makefiles.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/makefiles.md)
- [commit-messages.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/commit-messages.md)
- [branching.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/branching.md)
- [packages-and-dependencies.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/packages-and-dependencies.md)
- [pull-requests.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/pull-requests.md)
- [python-coding.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/python-coding.md)
- [knowledge/build-and-checks.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/build-and-checks.md)

## Development Model

Development runs in Docker through the `make` targets, see [local-development.md](local-development.md).

## Code Organization

- Tool logic that both servers share must live in [`mpt_mcp/mcp_tools.py`](../mpt_mcp/mcp_tools.py); `server_tools.py`, `server_resources.py` and `server_stdio.py` only register tools and wire the transport.
- HTTP tools must get the caller's credentials with `call_context: CallContext = Depends(get_call_context)`, not by reading request headers.
- Cross-cutting request behaviour (log context, analytics) must live in FastMCP middlewares, not in tools.
- Development-only stdio tools must be tagged with `DEBUG_TAG`.
- Tool docstrings are the descriptions MCP clients send to the model; treat changes to them as user-facing changes.
- Analytics schema changes must go through an Alembic migration, see [migrations.md](migrations.md).

## Lint Configuration

The lint settings live in [`pyproject.toml`](../pyproject.toml). Entries marked `TBD` in the ruff `ignore`, flake8 `extend-ignore` and mypy `disable_error_code` lists are existing violations still to be fixed, with their count. Fix a rule across the repository and remove its entry; do not add new violations.

## Validation Before Review

```bash
make check
make test
```

CI runs the same checks, and `pre-commit` runs them on every commit.
