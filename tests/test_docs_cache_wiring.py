from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from src import server_docs, server_resources, server_tools

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@dataclass
class _StubDocsCache:
    enabled: bool = True
    resources: list[dict[str, Any]] | None = None
    content_by_uri: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.resources is None:
            self.resources = [
                {
                    "uri": "docs://readme",
                    "name": "Home",
                    "description": "Documentation page: Home",
                    "mimeType": "text/markdown",
                    "metadata": {"path": "readme", "title": "Home", "browser_url": "https://example.test/readme"},
                    "content": None,
                }
            ]
        if self.content_by_uri is None:
            self.content_by_uri = {"docs://readme": "# Home\n\nHello"}

        # Used by `server_resources.get_documentation_resource` for cache-hit checks
        self._resources: dict[str, dict[str, Any]] = {r["uri"]: {"content": self.content_by_uri.get(r["uri"])} for r in self.resources if "uri" in r}

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    async def list_resources(self, **_: Any) -> list[dict[str, Any]]:
        assert self.resources is not None
        return self.resources

    async def get_resource(self, uri: str) -> str | None:
        assert self.content_by_uri is not None
        return self.content_by_uri.get(uri)


class _FakeMCP:
    def __init__(self) -> None:
        self._resources_by_uri: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {}

    def resource(self, uri: str, **_: Any) -> Callable[[Callable[..., Coroutine[Any, Any, str]]], Callable[..., Coroutine[Any, Any, str]]]:
        def _decorator(fn: Callable[..., Coroutine[Any, Any, str]]) -> Callable[..., Coroutine[Any, Any, str]]:
            self._resources_by_uri[uri] = fn
            return fn

        return _decorator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_docs_list_uses_live_server_docs_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Regression test for a subtle Python import bug:

    If `server_tools` imports `documentation_cache` by value, it stays bound to None.
    The fix is to read `server_docs.documentation_cache` dynamically after init.
    """

    stub = _StubDocsCache()

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    server_docs.documentation_cache = None

    result = await server_tools.marketplace_docs_list(limit=5)

    assert "error" not in result
    assert result["total"] == 1
    assert result["resources"][0]["uri"] == "docs://readme"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docs_resource_reader_uses_live_server_docs_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensures the `docs://{path}` resource handler reads the live `server_docs.documentation_cache`.
    """

    stub = _StubDocsCache()

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    server_docs.documentation_cache = None

    mcp = _FakeMCP()
    server_resources.register_http_resources(mcp)

    docs_handler = mcp._resources_by_uri["docs://{path}"]
    content = await docs_handler("readme")

    assert "Hello" in content
