from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest

from src import server_docs, server_resources, server_tools

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@dataclass
class _StubEnabledDocsCache:
    resources: list[dict[str, Any]]
    index: dict[str, Any]
    content_by_uri: dict[str, str]

    @property
    def is_enabled(self) -> bool:  # matches DocumentationCache interface
        return True

    async def list_resources(self, **_: Any) -> list[dict[str, Any]]:
        return self.resources

    async def get_documentation_index(self) -> dict[str, Any]:
        return self.index

    async def get_resource(self, uri: str) -> str | None:
        return self.content_by_uri.get(uri)

    def get_cache_info(self) -> dict[str, Any]:
        return {"resource_count": len(self.resources), "last_refresh": "now", "enabled": True}


class _FakeMCP:
    def __init__(self) -> None:
        self._resources_by_uri: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {}

    def resource(self, uri: str, **_: Any) -> Callable[[Callable[..., Coroutine[Any, Any, str]]], Callable[..., Coroutine[Any, Any, str]]]:
        def _decorator(fn: Callable[..., Coroutine[Any, Any, str]]) -> Callable[..., Coroutine[Any, Any, str]]:
            self._resources_by_uri[uri] = fn
            return fn

        return _decorator


class _FakeToolMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, fn=None):
        def _decorator(f):
            self.tools[getattr(f, "__name__", str(f))] = f
            return f

        return _decorator(fn) if fn is not None else _decorator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_docs_index_returns_cache_index(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEnabledDocsCache(
        resources=[{"uri": "docs://readme", "metadata": {"browser_url": "https://example.test/readme"}}],
        index={"total_pages": 1, "sections": [{"name": "readme", "total_pages": 1, "subsections": []}]},
        content_by_uri={"docs://readme": "hi"},
    )

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    monkeypatch.setattr(server_docs, "documentation_cache", None, raising=False)

    mcp = _FakeToolMCP()
    server_tools.register_http_tools(mcp)
    docs_index_fn = mcp.tools["marketplace_docs_index"]

    result = await docs_index_fn()
    assert result == stub.index


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_docs_list_happy_path_includes_browser_url(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEnabledDocsCache(
        resources=[
            {
                "uri": "docs://help-and-support/contact-support",
                "name": "Contact Support",
                "description": "Documentation page: Contact Support",
                "mimeType": "text/markdown",
                "metadata": {"browser_url": "https://example.test/contact-support"},
            }
        ],
        index={"total_pages": 1, "sections": []},
        content_by_uri={"docs://help-and-support/contact-support": "# Contact"},
    )

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    monkeypatch.setattr(server_docs, "documentation_cache", None, raising=False)

    result = await server_tools.marketplace_docs_list(search="contact", limit=100)
    assert result["total"] == 1
    assert result["resources"][0]["browser_url"] == "https://example.test/contact-support"
    assert "Prefer showing users the browser_url" in result["usage"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_docs_list_tip_when_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEnabledDocsCache(
        resources=[{"uri": f"docs://p/{i}", "metadata": {}} for i in range(10)],
        index={"total_pages": 10, "sections": []},
        content_by_uri={},
    )

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    monkeypatch.setattr(server_docs, "documentation_cache", None, raising=False)

    result = await server_tools.marketplace_docs_list(limit=5)
    assert result["total"] == 10  # list_resources returns all, tool reports returned count (not capped here)
    assert "tip" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_resources_info_reflects_docs_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEnabledDocsCache(
        resources=[{"uri": "docs://readme", "metadata": {}}],
        index={"total_pages": 1, "sections": []},
        content_by_uri={"docs://readme": "hi"},
    )

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    monkeypatch.setattr(server_docs, "documentation_cache", stub, raising=False)

    mcp = _FakeToolMCP()
    server_tools.register_http_tools(mcp)
    resources_info_fn = mcp.tools["marketplace_resources_info"]

    result = await resources_info_fn()
    assert result["documentation"]["enabled"] is True
    assert result["documentation"]["total_pages"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docs_resource_handler_reads_from_live_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEnabledDocsCache(
        resources=[{"uri": "docs://readme", "metadata": {}}],
        index={"total_pages": 1, "sections": []},
        content_by_uri={"docs://readme": "# Home\n\nHello"},
    )

    # The docs resource handler checks `_resources` for cache-hit; provide that attribute.
    stub._resources = {"docs://readme": {"content": "# Home\n\nHello"}}  # type: ignore[attr-defined]

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    monkeypatch.setattr(server_docs, "documentation_cache", None, raising=False)

    mcp = _FakeMCP()
    server_resources.register_http_resources(mcp)
    handler = mcp._resources_by_uri["docs://{path}"]
    content = await handler("readme")
    assert "Hello" in content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docs_resource_handler_returns_not_found_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEnabledDocsCache(
        resources=[{"uri": "docs://readme", "metadata": {}}],
        index={"total_pages": 1, "sections": []},
        content_by_uri={},  # missing
    )
    stub._resources = {"docs://readme": {"content": None}}  # type: ignore[attr-defined]

    async def _init() -> None:
        server_docs.documentation_cache = stub

    monkeypatch.setattr(server_docs, "initialize_documentation_cache", _init, raising=True)
    monkeypatch.setattr(server_docs, "documentation_cache", None, raising=False)

    mcp = _FakeMCP()
    server_resources.register_http_resources(mcp)
    handler = mcp._resources_by_uri["docs://{path}"]
    content = await handler("readme")
    assert "Documentation page not found" in content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_docs_reinitializes_when_pid_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force a mismatch between "last init pid" and current pid, and ensure we clear cached state.
    monkeypatch.setattr(server_docs, "_docs_cache_initialized", True, raising=False)
    monkeypatch.setattr(server_docs, "_docs_cache_init_pid", 999999, raising=False)
    monkeypatch.setattr(server_docs, "documentation_cache", Mock(), raising=False)

    # Also force "not configured" path so no GitBook network calls occur.
    monkeypatch.setattr(server_docs.config, "gitbook_api_key", "", raising=False)
    monkeypatch.setattr(server_docs.config, "gitbook_space_id", "", raising=False)

    await server_docs.initialize_documentation_cache()

    assert server_docs._docs_cache_initialized is True
    assert server_docs._docs_cache_init_pid == server_docs.os.getpid()
    assert server_docs.documentation_cache is not None
    assert getattr(server_docs.documentation_cache, "is_enabled", False) is False
