import datetime as dt
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from mpt_mcp.documentation.cache import DocumentationCache
from mpt_mcp.documentation.gitbook import GitBookClient


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


@pytest.fixture
def cache(mock_gitbook_client):
    return DocumentationCache(gitbook_client=mock_gitbook_client)


@pytest.fixture
def cache_factory(mock_gitbook_client):
    async def factory(pages, **cache_args):
        mock_gitbook_client.fetch_space_content.return_value = {"pages": pages}
        cache = DocumentationCache(gitbook_client=mock_gitbook_client, **cache_args)
        await cache.refresh()
        return cache

    return factory


def test_cache_initialization_with_client(mock_gitbook_client):
    result = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=24)

    assert result.is_enabled is True
    assert result.refresh_interval == dt.timedelta(hours=24)


def test_cache_initialization_without_client():
    result = DocumentationCache(gitbook_client=None)

    assert result.is_enabled is False


def test_needs_refresh_when_empty(mock_gitbook_client):
    result = DocumentationCache(gitbook_client=mock_gitbook_client)

    assert result.needs_refresh is True


async def test_refresh_success(cache):
    result = await cache.refresh()

    cache_info = cache.get_cache_info()
    assert (result, cache_info["has_content"], cache_info["resource_count"]) == (True, True, 2)
    assert cache_info["last_refresh"] is not None


async def test_refresh_builds_resource_index(cache):
    await cache.refresh()  # act

    resources = {resource["uri"]: resource for resource in await cache.list_resources()}
    assert set(resources) == {"docs://getting-started", "docs://api-reference"}
    assert (
        resources["docs://getting-started"]["name"],
        resources["docs://getting-started"]["mimeType"],
    ) == ("Getting Started", "text/markdown")


async def test_refresh_indexes_nested_pages(cache_factory):
    cache = await cache_factory(
        [
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
        ],
    )

    result = {resource["uri"] for resource in await cache.list_resources()}

    assert result == {
        "docs://getting-started",
        "docs://getting-started/installation",
        "docs://getting-started/configuration",
        "docs://api-reference",
        "docs://api-reference/orders",
    }


async def test_refresh_request_failure(cache, mock_gitbook_client):
    mock_gitbook_client.fetch_space_content.side_effect = httpx.ConnectError("Connection refused")

    result = await cache.refresh()

    assert (result, cache.get_cache_info()["has_content"]) == (False, False)


async def test_refresh_disabled_cache():
    cache = DocumentationCache(gitbook_client=None)

    result = await cache.refresh()

    assert result is False


async def test_list_resources(cache):
    await cache.refresh()

    result = await cache.list_resources()

    assert len(result) == 2
    assert any(resource["uri"] == "docs://getting-started" for resource in result)


async def test_list_resources_with_section_filter(cache_factory):
    cache = await cache_factory(
        [
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
        ],
    )

    result = await cache.list_resources(section="developer-resources")

    assert len(result) == 2
    assert all("developer-resources" in resource["uri"] for resource in result)


async def test_list_resources_with_subsection_filter(cache_factory):
    cache = await cache_factory(
        [
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
        ],
    )

    result = await cache.list_resources(subsection="rest-api")

    assert len(result) == 2
    assert all("rest-api" in resource["uri"] for resource in result)


async def test_list_resources_with_search(cache_factory):
    cache = await cache_factory(
        [
            {
                "id": "page1",
                "title": "Billing Overview",
                "path": "modules/billing/overview",
            },
            {"id": "page2", "title": "Invoices", "path": "modules/billing/invoices"},
            {"id": "page3", "title": "Orders", "path": "modules/commerce/orders"},
        ],
    )

    result = await cache.list_resources(search="billing")

    assert len(result) == 2
    searched_texts = [f"{resource['name']} {resource['uri']}".lower() for resource in result]
    assert all("billing" in text for text in searched_texts)


async def test_list_resources_with_limit(cache_factory):
    cache = await cache_factory(
        [
            {"id": f"page{index}", "title": f"Page {index}", "path": f"section/page-{index}"}
            for index in range(10)
        ],
    )

    result = await cache.list_resources(limit=5)

    assert len(result) == 5


async def test_list_resources_combined_filters(cache_factory):
    cache = await cache_factory(
        [
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
        ],
    )

    result = await cache.list_resources(section="developer-resources", search="billing")

    assert len(result) == 1
    assert result[0]["name"] == "Billing API"


async def test_list_resources_with_public_url(cache_factory):
    cache = await cache_factory(
        [
            {
                "id": "page1",
                "title": "Contact Support",
                "path": "help-and-support/contact-support",
            },
            {"id": "page2", "title": "Billing", "path": "developer-resources/billing"},
        ],
        public_url="https://docs.example.com",
    )

    result = await cache.list_resources()

    browser_urls = {resource["uri"]: resource["metadata"]["browser_url"] for resource in result}
    assert browser_urls == {
        "docs://help-and-support/contact-support": (
            "https://docs.example.com/help-and-support/contact-support"
        ),
        "docs://developer-resources/billing": "https://docs.example.com/developer-resources/billing",
    }


async def test_get_documentation_index(cache_factory):
    cache = await cache_factory(
        [
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
        ],
    )

    result = await cache.get_documentation_index()

    assert result["total_pages"] == 4
    assert {
        section["name"]: (
            section["total_pages"],
            {subsection["name"]: subsection["pages"] for subsection in section["subsections"]},
        )
        for section in result["sections"]
    } == {
        "developer-resources": (2, {"rest-api": 2}),
        "help-and-support": (2, {"faqs": 1, "contact-support": 1}),
    }


async def test_get_resource_success(cache):
    await cache.refresh()

    result = await cache.get_resource("docs://getting-started")

    assert result is not None
    assert "Getting Started" in result


async def test_get_resource_not_found(cache):
    await cache.refresh()

    result = await cache.get_resource("docs://non-existent")

    assert result is None


async def test_get_resource_request_failure(cache, mock_gitbook_client):
    await cache.refresh()
    mock_gitbook_client.fetch_page_by_id.side_effect = httpx.ConnectError("Connection refused")

    result = await cache.get_resource("docs://getting-started")

    assert result == "Error fetching content: Connection refused"


async def test_ensure_cached_refreshes_if_needed(cache, mock_gitbook_client):
    await cache.ensure_cached()  # act

    assert cache.get_cache_info()["has_content"] is True
    mock_gitbook_client.fetch_space_content.assert_awaited_once()


def test_get_cache_info(cache):
    result = cache.get_cache_info()

    assert result["enabled"] is True
    assert result["has_content"] is False
    assert result["needs_refresh"] is True
    assert result["resource_count"] == 0
    assert result["refresh_interval_hours"] == 24


async def test_needs_refresh_false_right_after_refresh(mock_gitbook_client):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=1)
    await cache.refresh()

    result = cache.needs_refresh

    assert result is False


async def test_needs_refresh_after_refresh_interval(mock_gitbook_client, monkeypatch):
    cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=1)
    await cache.refresh()
    two_hours_later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)
    monkeypatch.setattr(
        "mpt_mcp.documentation.cache.dt",
        Mock(datetime=Mock(now=Mock(return_value=two_hours_later))),
    )

    result = cache.needs_refresh

    assert result is True


async def test_get_resource_without_markdown(cache, mock_gitbook_client):
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
    await cache.refresh()

    result = await cache.get_resource("docs://getting-started")

    assert all(
        text in result for text in ("Header text", "Paragraph 1", "Paragraph 2", "Nested text")
    )
