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

Development runs in Docker through the `make` targets, see [local-development.md](local-development.md). Where new code goes and the rules each layer follows are in [architecture.md](architecture.md#design-rules).

## Lint Configuration

The lint settings live in [`pyproject.toml`](../pyproject.toml). Entries marked `TBD` in the ruff `ignore`, flake8 `extend-ignore` and mypy `disable_error_code` lists are existing violations still to be fixed, with their count. Fix a rule across the repository and remove its entry; do not add new violations.

## Validation Before Review

```bash
make check
make test
```

CI runs the same checks, and `pre-commit` runs them on every commit.
