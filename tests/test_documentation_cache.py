import datetime as dt
from unittest.mock import AsyncMock, Mock

import pytest

from mpt_mcp.documentation_cache import DocumentationCache
from mpt_mcp.gitbook_client import GitBookClient


@pytest.fixture
def mock_gitbook_client():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {"id": "page1", "title": "Getting Started", "path": "getting-started"},
                {"id": "page2", "title": "API Reference", "path": "api-reference"},
            ]
        }
    )
    client.fetch_page_by_path = AsyncMock(
        return_value={
            "id": "page1",
            "title": "Getting Started",
            "markdown": "# Getting Started\n\nWelcome!",
        }
    )
    client.fetch_page_by_id = AsyncMock(
        return_value={
            "id": "page1",
            "title": "Getting Started",
            "markdown": "# Getting Started\n\nWelcome!",
        }
    )
    return client


def test_cache_initialization_with_client(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=24)  # act

    assert cache.is_enabled is True
    assert cache.refresh_interval == dt.timedelta(hours=24)


def test_cache_initialization_without_client():
    cache = DocumentationCache(gitbook_client=None)  # act

    assert cache.is_enabled is False


def test_needs_refresh_when_empty(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)  # act

    assert cache.needs_refresh is True


@pytest.mark.asyncio
async def test_refresh_success(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)

    success = await cache.refresh()

    info = cache.get_cache_info()
    assert (success, info["has_content"], info["resource_count"]) == (True, True, 2)
    assert info["last_refresh"] is not None


@pytest.mark.asyncio
async def test_refresh_builds_resource_index(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)

    await cache.refresh()

    resources = {resource["uri"]: resource for resource in await cache.list_resources()}
    assert set(resources) == {"docs://getting-started", "docs://api-reference"}
    assert (
        resources["docs://getting-started"]["name"],
        resources["docs://getting-started"]["mimeType"],
    ) == ("Getting Started", "text/markdown")


@pytest.mark.asyncio
async def test_refresh_builds_resource_index_with_nested_pages():
    # Mock client with nested page structure
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Getting Started",
                    "path": "getting-started",
                    "pages": [
                        {
                            "id": "page1-1",
                            "title": "Installation",
                            "path": "getting-started/installation",
                        },
                        {
                            "id": "page1-2",
                            "title": "Configuration",
                            "path": "getting-started/configuration",
                        },
                    ],
                },
                {
                    "id": "page2",
                    "title": "API Reference",
                    "path": "api-reference",
                    "pages": [{"id": "page2-1", "title": "Orders", "path": "api-reference/orders"}],
                },
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    result = {resource["uri"] for resource in await cache.list_resources()}

    assert result == {
        "docs://getting-started",
        "docs://getting-started/installation",
        "docs://getting-started/configuration",
        "docs://api-reference",
        "docs://api-reference/orders",
    }


@pytest.mark.asyncio
async def test_refresh_disabled_cache():
    cache = DocumentationCache(gitbook_client=None)

    success = await cache.refresh()

    assert success is False


@pytest.mark.asyncio
async def test_list_resources(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)
    await cache.refresh()

    resources = await cache.list_resources()

    assert len(resources) == 2
    assert any(r["uri"] == "docs://getting-started" for r in resources)


@pytest.mark.asyncio
async def test_list_resources_with_section_filter():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Orders API",
                    "path": "developer-resources/rest-api/orders",
                },
                {
                    "id": "page2",
                    "title": "Billing API",
                    "path": "developer-resources/rest-api/billing",
                },
                {"id": "page3", "title": "FAQ", "path": "help-and-support/faqs"},
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    # Filter by developer-resources section
    resources = await cache.list_resources(section="developer-resources")

    assert len(resources) == 2
    assert all("developer-resources" in r["uri"] for r in resources)


@pytest.mark.asyncio
async def test_list_resources_with_subsection_filter():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Orders API",
                    "path": "developer-resources/rest-api/orders",
                },
                {
                    "id": "page2",
                    "title": "Billing API",
                    "path": "developer-resources/rest-api/billing",
                },
                {
                    "id": "page3",
                    "title": "Design System",
                    "path": "developer-resources/design-system/colors",
                },
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    # Filter by rest-api subsection
    resources = await cache.list_resources(subsection="rest-api")

    assert len(resources) == 2
    assert all("rest-api" in r["uri"] for r in resources)


@pytest.mark.asyncio
async def test_list_resources_with_search():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Billing Overview",
                    "path": "modules/billing/overview",
                },
                {"id": "page2", "title": "Invoices", "path": "modules/billing/invoices"},
                {"id": "page3", "title": "Orders", "path": "modules/commerce/orders"},
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    # Search for "billing"
    resources = await cache.list_resources(search="billing")

    assert len(resources) == 2
    assert all("billing" in r["name"].lower() or "billing" in r["uri"].lower() for r in resources)


@pytest.mark.asyncio
async def test_list_resources_with_limit():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {"id": f"page{i}", "title": f"Page {i}", "path": f"section/page-{i}"}
                for i in range(10)
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    # Limit to 5 results
    resources = await cache.list_resources(limit=5)

    assert len(resources) == 5


@pytest.mark.asyncio
async def test_list_resources_combined_filters():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Billing API",
                    "path": "developer-resources/rest-api/billing",
                },
                {
                    "id": "page2",
                    "title": "Orders API",
                    "path": "developer-resources/rest-api/orders",
                },
                {
                    "id": "page3",
                    "title": "Billing FAQ",
                    "path": "help-and-support/faqs/billing",
                },
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    # Filter by section AND search for "billing"
    resources = await cache.list_resources(section="developer-resources", search="billing")

    assert len(resources) == 1
    assert resources[0]["name"] == "Billing API"


@pytest.mark.asyncio
async def test_list_resources_includes_browser_url_when_public_url_set():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Contact Support",
                    "path": "help-and-support/contact-support",
                },
                {"id": "page2", "title": "Billing", "path": "developer-resources/billing"},
            ]
        }
    )
    cache = DocumentationCache(
        gitbook_client=client,
        public_url="https://docs.example.com",
    )
    await cache.refresh()

    resources = await cache.list_resources()

    assert len(resources) == 2
    for r in resources:
        assert "metadata" in r
        assert "browser_url" in r["metadata"], f"Expected metadata.browser_url for {r['uri']}"
    uris_to_browser_url = {r["uri"]: r["metadata"]["browser_url"] for r in resources}
    assert (
        uris_to_browser_url.get("docs://help-and-support/contact-support")
        == "https://docs.example.com/help-and-support/contact-support"
    )
    assert (
        uris_to_browser_url.get("docs://developer-resources/billing")
        == "https://docs.example.com/developer-resources/billing"
    )


@pytest.mark.asyncio
async def test_get_documentation_index():
    client = Mock(spec=GitBookClient)
    client.fetch_space_content = AsyncMock(
        return_value={
            "pages": [
                {
                    "id": "page1",
                    "title": "Orders API",
                    "path": "developer-resources/rest-api/orders",
                },
                {
                    "id": "page2",
                    "title": "Billing API",
                    "path": "developer-resources/rest-api/billing",
                },
                {"id": "page3", "title": "FAQ", "path": "help-and-support/faqs/general"},
                {"id": "page4", "title": "Contact", "path": "help-and-support/contact-support"},
            ]
        }
    )

    cache = DocumentationCache(gitbook_client=client)
    await cache.refresh()

    index = await cache.get_documentation_index()

    assert index["total_pages"] == 4
    assert len(index["sections"]) == 2

    # Check developer-resources section
    dev_section = next(s for s in index["sections"] if s["name"] == "developer-resources")
    assert dev_section["total_pages"] == 2
    assert len(dev_section["subsections"]) == 1
    assert dev_section["subsections"][0]["name"] == "rest-api"
    assert dev_section["subsections"][0]["pages"] == 2

    # Check help-and-support section
    help_section = next(s for s in index["sections"] if s["name"] == "help-and-support")
    assert help_section["total_pages"] == 2
    assert len(help_section["subsections"]) == 2


@pytest.mark.asyncio
async def test_get_resource_success(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)
    await cache.refresh()

    content = await cache.get_resource("docs://getting-started")

    assert content is not None
    assert "Getting Started" in content


@pytest.mark.asyncio
async def test_get_resource_not_found(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)
    await cache.refresh()

    content = await cache.get_resource("docs://non-existent")

    assert content is None


@pytest.mark.asyncio
async def test_ensure_cached_refreshes_if_needed(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)

    await cache.ensure_cached()  # act

    assert cache.get_cache_info()["has_content"] is True
    mock_gitbook_client.fetch_space_content.assert_awaited_once()


def test_get_cache_info(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)

    info = cache.get_cache_info()  # act

    assert info["enabled"] is True
    assert info["has_content"] is False
    assert info["needs_refresh"] is True
    assert info["resource_count"] == 0
    assert info["refresh_interval_hours"] == 24


@pytest.mark.asyncio
async def test_needs_refresh_false_right_after_refresh(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=1)
    await cache.refresh()

    result = cache.needs_refresh

    assert result is False


@pytest.mark.asyncio
async def test_needs_refresh_after_refresh_interval(mock_gitbook_client, monkeypatch):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=1)
    await cache.refresh()
    two_hours_later = dt.datetime.now() + dt.timedelta(hours=2)
    monkeypatch.setattr(
        "mpt_mcp.documentation_cache.dt",
        Mock(datetime=Mock(now=Mock(return_value=two_hours_later))),
    )

    result = cache.needs_refresh

    assert result is True


@pytest.mark.asyncio
async def test_get_resource_extracts_text_when_page_has_no_markdown(mock_gitbook_client):
    document = {
        "nodes": [
            {
                "type": "paragraph",
                "nodes": [{"object": "text", "leaves": [{"text": "Header text"}]}],
            },
            {
                "type": "paragraph",
                "nodes": [{"object": "text", "leaves": [{"text": "Paragraph 1"}]}],
            },
            {
                "type": "paragraph",
                "nodes": [
                    {"object": "text", "leaves": [{"text": "Paragraph 2"}]},
                    {"text": "Nested text"},
                ],
            },
        ]
    }

    mock_gitbook_client.fetch_page_by_id.return_value = {"id": "page1", "document": document}
    cache = DocumentationCache(gitbook_client=mock_gitbook_client)
    await cache.refresh()

    result = await cache.get_resource("docs://getting-started")

    assert all(
        text in result for text in ("Header text", "Paragraph 1", "Paragraph 2", "Nested text")
    )
