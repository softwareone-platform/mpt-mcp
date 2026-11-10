# Testing

Shared unit-test rules live in [unittests.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/unittests.md).

Shared build and target knowledge also applies:

- [knowledge/build-and-checks.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/build-and-checks.md)
- [knowledge/make-targets.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/make-targets.md)

This file documents repository-specific testing behaviour.

## Test Scope

All tests are unit tests: external systems (Marketplace API, GitBook, PostgreSQL, JWKS endpoints) are mocked and no test makes network calls. There are no integration or end-to-end tests in the suite. To check a running server against the real Marketplace API, run [`examples/smoke_test.py`](../examples/smoke_test.py) by hand or paste [`examples/chat_check_prompt.md`](../examples/chat_check_prompt.md) in an MCP client, as described in [examples/README.md](../examples/README.md#checking-the-server).

The layout mirrors the package:

- one [`tests/test_<module>.py`](../tests) per module in [`mpt_mcp/`](../mpt_mcp), for example `tests/test_config.py` for `mpt_mcp/config.py`, and `tests/tools/query/test_tool.py` for `mpt_mcp/tools/query/tool.py`
- [`tests/analytics/`](../tests/analytics) for the [`mpt_mcp/analytics/`](../mpt_mcp/analytics) subpackage
- [`tests/runtime/`](../tests/runtime) for the [`mpt_mcp/runtime/`](../mpt_mcp/runtime) subpackage
- [`tests/tools/`](../tests/tools) for the [`mpt_mcp/tools/`](../mpt_mcp/tools) subpackage
- [`tests/marketplace/`](../tests/marketplace) and [`tests/auth/`](../tests/auth) for the [`mpt_mcp/marketplace/`](../mpt_mcp/marketplace) and [`mpt_mcp/auth/`](../mpt_mcp/auth) subpackages
- [`tests/documentation/`](../tests/documentation) for the [`mpt_mcp/documentation/`](../mpt_mcp/documentation) subpackage

Add a test where the behaviour lives: each tool and its logic in the `tests/tools/` file of its module, with the fixtures they share in [`tests/tools/conftest.py`](../tests/tools/conftest.py), tool registration and visibility in `test_server.py`, documentation tools and the `docs://` resource in `tests/documentation/test_server.py`, the health check and HTTP routing in `tests/runtime/test_http.py`, which builds the app with `create_http_app()` instead of importing `mpt_mcp.runtime.main`.

## Commands

```bash
make test
make check
make check-all
```

Repository command mapping:

- `make test` runs `pytest` with coverage (`coverage.xml` is used by SonarCloud)
- `make check` runs `ruff format --check`, `ruff check`, `flake8`, `mypy` and `uv lock --check`
- `make check-all` runs both

## Pytest Configuration

Repository-specific settings come from [`pyproject.toml`](../pyproject.toml):

- tests are discovered under `tests`, with the repository root in `pythonpath`
- `asyncio_mode = "auto"`: async tests run without `@pytest.mark.asyncio`
- coverage is collected for `mpt_mcp` with branch coverage
- tests run with `--import-mode=importlib`

## Writing Tests

Repository-specific guidance:

- call tools as the module functions of `tools/` or `documentation/server.py` and pass their dependencies explicitly (`call_context`, `api_client`, or `spec` from the `spec_factory` fixture of [`tests/tools/conftest.py`](../tests/tools/conftest.py)) instead of building HTTP requests; check argument validation and the input schema with an in-memory `fastmcp.Client`
- patch names where they are used, for example `mpt_mcp.documentation.store.load_documentation_cache`
- the `docs_cache_factory` and `doc_page_factory` fixtures in [`tests/conftest.py`](../tests/conftest.py) build a fake documentation cache: pass it as `docs_cache` to the documentation tools, and servers created in the test load it from their documentation store
- pass a `MarketplaceSpecStore`, or a mock of it, to the functions that take `spec_store`; servers created with `create_mcp_server()` get a new store from `spec_lifespan`
- pass a `TokenValidator`, or a mock of it, to `create_api_client()` and to the functions that take `token_validator`; each new `TokenValidator` starts with empty validation and JWKS caches
- test JWT validation with real RSA keys and mocked HTTP responses, as in `tests/auth/test_token_validator.py`
- debug tool visibility depends on `DEBUG`, which `compose.yaml` sets to `true`: test it on servers created with `config.debug` set, as the `production_server` and `debug_server` fixtures in `test_server.py` do

## When Tests Are Required

Add or update tests when a change modifies:

- tool behaviour, parameters or error payloads
- request handling, credentials or token validation
- middlewares, logging context or analytics events
- endpoint discovery or OpenAPI parsing

If a change only affects documentation, tests are not required.
