from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ResourceError, ToolError

from mpt_mcp.documentation import server
from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.lifespan import documentation_store_lifespan
from mpt_mcp.tools.results import CHARACTER_LIMIT

LINE_COUNT = 1000
LINE_LENGTH = 95


@pytest.fixture
def docs_server():
    mcp = FastMCP("test", lifespan=documentation_store_lifespan)
    mcp.add_provider(server.documentation_provider)
    return mcp


async def test_docs_list_exposes_browser_url_and_note():
    mock_resources = [
        {
            "uri": "docs://help-and-support/contact-support",
            "name": "Contact Support",
            "description": "Documentation page: Contact Support",
            "mimeType": "text/markdown",
            "metadata": {
                "id": "7qHvpiUID0CAu2h8cXUr",
                "path": "help-and-support/contact-support",
                "title": "Contact Support",
                "browser_url": "https://docs.example.com/help-and-support/contact-support",
            },
        },
    ]
    mock_cache = Mock(
        spec=DocumentationCache,
        is_enabled=True,
        list_resources=AsyncMock(return_value=mock_resources),
    )

    result = (
        await server.marketplace_docs_list(search="contact support", docs_cache=mock_cache)
    ).model_dump()

    assert result["total"] == 1
    assert len(result["resources"]) == 1
    assert (
        result["resources"][0]["browser_url"]
        == "https://docs.example.com/help-and-support/contact-support"
    )
    assert "Prefer showing users the browser_url" in result["usage"]
    assert "do not show internal uri or id" in result["usage"]


async def test_docs_list_without_browser_url_metadata():
    mock_resources = [
        {
            "uri": "docs://some/page",
            "name": "Some Page",
            "description": "A page",
            "mimeType": "text/markdown",
            "metadata": {"id": "abc", "path": "some/page", "title": "Some Page"},
        },
    ]
    mock_cache = Mock(
        spec=DocumentationCache,
        is_enabled=True,
        list_resources=AsyncMock(return_value=mock_resources),
    )

    result = (await server.marketplace_docs_list(search="some", docs_cache=mock_cache)).model_dump()

    assert result["total"] == 1
    assert "browser_url" not in result["resources"][0]
    assert "Prefer showing users the browser_url" in result["usage"]


async def test_docs_index_without_cache_fails():
    disabled_cache = Mock(spec=DocumentationCache, is_enabled=False)

    with pytest.raises(ToolError, match="Documentation cache is not available"):
        await server.marketplace_docs_index(docs_cache=disabled_cache)


async def test_docs_index_returns_cache_index(docs_cache_factory):
    index = {
        "total_pages": 1,
        "sections": [{"name": "readme", "total_pages": 1, "subsections": []}],
    }
    cache = docs_cache_factory(resources=[{"uri": "docs://readme", "metadata": {}}], index=index)

    result = (await server.marketplace_docs_index(docs_cache=cache)).model_dump()

    assert result == index


async def test_docs_list_includes_browser_url_and_usage(docs_cache_factory, doc_page_factory):
    cache = docs_cache_factory(
        resources=[
            doc_page_factory(
                "docs://help-and-support/contact-support",
                browser_url="https://example.test/contact-support",
            )
        ]
    )

    result = (
        await server.marketplace_docs_list(search="contact", limit=100, docs_cache=cache)
    ).model_dump()

    assert (result["total"], result["resources"][0]["browser_url"]) == (
        1,
        "https://example.test/contact-support",
    )
    assert "Prefer showing users the browser_url" in result["usage"]


async def test_marketplace_docs_list_tip_when_limited(docs_cache_factory, doc_page_factory):
    resources = [doc_page_factory(f"docs://p/{index}") for index in range(10)]
    cache = docs_cache_factory(resources=resources)

    result = (await server.marketplace_docs_list(limit=5, docs_cache=cache)).model_dump()

    assert "tip" in result


async def test_docs_list_uses_live_docs_cache(docs_cache_factory, doc_page_factory):
    cache = docs_cache_factory(resources=[doc_page_factory("docs://readme")])

    result = (await server.marketplace_docs_list(limit=5, docs_cache=cache)).model_dump()

    first_uri = result["resources"][0]["uri"]
    assert (result["total"], first_uri) == (1, "docs://readme")


async def test_docs_read_returns_text_and_count(docs_cache_factory):
    cache = docs_cache_factory(
        content_by_uri={"docs://help-and-support/contact-support": "# Contact\n\nHello from docs."}
    )

    result = (
        await server.marketplace_docs_read(
            uri="docs://help-and-support/contact-support", docs_cache=cache
        )
    ).model_dump()

    assert result == {"text": "# Contact\n\nHello from docs.", "count": 1}


async def test_docs_read_splits_long_page(docs_cache_factory):
    line = "x" * LINE_LENGTH
    page = "\n".join(f"{index} {line}" for index in range(LINE_COUNT))
    cache = docs_cache_factory(content_by_uri={"docs://billing/charges": page})

    first = await server.marketplace_docs_read(uri="docs://billing/charges", docs_cache=cache)

    result = await server.marketplace_docs_read(
        uri="docs://billing/charges", offset=first.next_offset, docs_cache=cache
    )

    assert len(first.text) <= CHARACTER_LIMIT
    assert first.text.endswith("\n")
    assert first.total_characters == len(page)
    assert page.startswith(first.text + result.text)


async def test_docs_read_last_part_has_no_next_offset(docs_cache_factory):
    page = "x" * (CHARACTER_LIMIT + 10)
    cache = docs_cache_factory(content_by_uri={"docs://billing/charges": page})

    result = (
        await server.marketplace_docs_read(
            uri="docs://billing/charges", offset=CHARACTER_LIMIT, docs_cache=cache
        )
    ).model_dump()

    assert result == {"text": "x" * 10, "count": 1}


@pytest.mark.parametrize("offset", [-1, 100])
async def test_docs_read_offset_outside_page_fails(docs_cache_factory, offset):
    cache = docs_cache_factory(content_by_uri={"docs://readme": "# Readme"})

    with pytest.raises(ToolError, match="is outside the page"):
        await server.marketplace_docs_read(uri="docs://readme", offset=offset, docs_cache=cache)


async def test_docs_read_not_found_fails(docs_cache_factory):
    cache = docs_cache_factory()

    with pytest.raises(ToolError, match="Documentation page not found: docs://missing/page"):
        await server.marketplace_docs_read(uri="docs://missing/page", docs_cache=cache)


async def test_docs_resource_reads_from_live_docs_cache(docs_cache_factory):
    cache = docs_cache_factory(content_by_uri={"docs://readme": "# Home\n\nHello"})

    result = await server.get_documentation_page("readme", docs_cache=cache)

    assert result == "# Home\n\nHello"


async def test_docs_resource_not_found_when_missing(docs_cache_factory):
    cache = docs_cache_factory()

    with pytest.raises(ResourceError, match="Documentation page not found: docs://readme"):
        await server.get_documentation_page("readme", docs_cache=cache)


async def test_docs_resource_reads_nested_paths(docs_cache_factory, docs_server):
    docs_cache_factory(content_by_uri={"docs://help-and-support/contact-support": "# Contact"})

    async with Client(docs_server) as client:
        result = await client.read_resource("docs://help-and-support/contact-support")

    assert result[0].text == "# Contact"


async def test_server_serves_docs_tools_and_resource(docs_server):
    result = (
        {tool.name for tool in await docs_server.list_tools()},
        {template.uri_template for template in await docs_server.list_resource_templates()},
    )

    assert result == (
        {"marketplace_docs_index", "marketplace_docs_list", "marketplace_docs_read"},
        {"docs://{path*}"},
    )
