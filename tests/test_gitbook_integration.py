"""
Tests for GitBook integration - client, cache, and MCP resources
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.documentation_cache import DocumentationCache
from src.gitbook_client import GitBookClient


class TestGitBookClient:
    """Test GitBook API client"""

    @pytest.fixture
    def client(self):
        """Create a GitBook client instance"""
        return GitBookClient(api_key="test_api_key", space_id="test_space_id", base_url="https://api.gitbook.com/v1")

    def test_client_initialization(self, client):
        """Test client initializes correctly"""
        assert client.api_key == "test_api_key"
        assert client.space_id == "test_space_id"
        assert client.base_url == "https://api.gitbook.com/v1"

    def test_get_headers(self, client):
        """Test authentication headers are correct"""
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer test_api_key"
        assert headers["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_fetch_space_content(self, client):
        """Test fetching space content"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "pages": [
                {"id": "page1", "title": "Getting Started", "path": "getting-started"},
                {"id": "page2", "title": "API Reference", "path": "api-reference"},
            ]
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            content = await client.fetch_space_content()

            assert "pages" in content
            assert len(content["pages"]) == 2

    @pytest.mark.asyncio
    async def test_fetch_page_by_path(self, client):
        """Test fetching a specific page by path"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "page1",
            "title": "Getting Started",
            "path": "getting-started",
            "markdown": "# Getting Started\n\nWelcome to the docs!",
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            page = await client.fetch_page_by_path("getting-started")

            assert page["id"] == "page1"
            assert page["title"] == "Getting Started"
            assert "markdown" in page

    @pytest.mark.asyncio
    async def test_validate_credentials_success(self, client):
        """Test credential validation succeeds"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            is_valid = await client.validate_credentials()

            assert is_valid is True

    @pytest.mark.asyncio
    async def test_validate_credentials_failure(self, client):
        """Test credential validation fails"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(side_effect=Exception("Unauthorized"))
            mock_client.return_value = mock_context

            is_valid = await client.validate_credentials()

            assert is_valid is False


class TestDocumentationCache:
    """Test documentation cache manager"""

    @pytest.fixture
    def mock_gitbook_client(self):
        """Create a mock GitBook client"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(
            return_value={
                "pages": [
                    {"id": "page1", "title": "Getting Started", "path": "getting-started"},
                    {"id": "page2", "title": "API Reference", "path": "api-reference"},
                ]
            }
        )
        client.fetch_page_by_path = AsyncMock(return_value={"id": "page1", "title": "Getting Started", "markdown": "# Getting Started\n\nWelcome!"})
        client.fetch_page_by_id = AsyncMock(return_value={"id": "page1", "title": "Getting Started", "markdown": "# Getting Started\n\nWelcome!"})
        return client

    def test_cache_initialization_with_client(self, mock_gitbook_client):
        """Test cache initializes with GitBook client"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=24)

        assert cache.is_enabled is True
        assert cache.refresh_interval == timedelta(hours=24)

    def test_cache_initialization_without_client(self):
        """Test cache initializes without GitBook client (disabled)"""
        cache = DocumentationCache(gitbook_client=None)

        assert cache.is_enabled is False

    def test_needs_refresh_when_empty(self, mock_gitbook_client):
        """Test cache needs refresh when empty"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)

        assert cache.needs_refresh is True

    @pytest.mark.asyncio
    async def test_refresh_success(self, mock_gitbook_client):
        """Test cache refresh succeeds"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)

        success = await cache.refresh()

        assert success is True
        assert cache._content is not None
        assert cache._last_refresh is not None
        assert len(cache._resources) == 2

    @pytest.mark.asyncio
    async def test_refresh_builds_resource_index(self, mock_gitbook_client):
        """Test refresh builds correct resource index"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)

        await cache.refresh()

        assert "docs://getting-started" in cache._resources
        assert "docs://api-reference" in cache._resources

        resource = cache._resources["docs://getting-started"]
        assert resource["name"] == "Getting Started"
        assert resource["mimeType"] == "text/markdown"

    @pytest.mark.asyncio
    async def test_refresh_builds_resource_index_with_nested_pages(self):
        """Test refresh handles nested pages correctly"""
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
                            {"id": "page1-1", "title": "Installation", "path": "getting-started/installation"},
                            {"id": "page1-2", "title": "Configuration", "path": "getting-started/configuration"},
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

        # Should have 5 total pages (2 parent + 3 children)
        assert len(cache._resources) == 5
        assert "docs://getting-started" in cache._resources
        assert "docs://getting-started/installation" in cache._resources
        assert "docs://getting-started/configuration" in cache._resources
        assert "docs://api-reference" in cache._resources
        assert "docs://api-reference/orders" in cache._resources

    @pytest.mark.asyncio
    async def test_refresh_disabled_cache(self):
        """Test refresh on disabled cache returns False"""
        cache = DocumentationCache(gitbook_client=None)

        success = await cache.refresh()

        assert success is False

    @pytest.mark.asyncio
    async def test_list_resources(self, mock_gitbook_client):
        """Test listing all resources"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)
        await cache.refresh()

        resources = await cache.list_resources()

        assert len(resources) == 2
        assert any(r["uri"] == "docs://getting-started" for r in resources)

    @pytest.mark.asyncio
    async def test_list_resources_with_section_filter(self):
        """Test filtering resources by section"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(
            return_value={
                "pages": [
                    {"id": "page1", "title": "Orders API", "path": "developer-resources/rest-api/orders"},
                    {"id": "page2", "title": "Billing API", "path": "developer-resources/rest-api/billing"},
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
    async def test_list_resources_with_subsection_filter(self):
        """Test filtering resources by subsection"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(
            return_value={
                "pages": [
                    {"id": "page1", "title": "Orders API", "path": "developer-resources/rest-api/orders"},
                    {"id": "page2", "title": "Billing API", "path": "developer-resources/rest-api/billing"},
                    {"id": "page3", "title": "Design System", "path": "developer-resources/design-system/colors"},
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
    async def test_list_resources_with_search(self):
        """Test searching resources by keyword"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(
            return_value={
                "pages": [
                    {"id": "page1", "title": "Billing Overview", "path": "modules/billing/overview"},
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
    async def test_list_resources_with_limit(self):
        """Test limiting number of results"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(return_value={"pages": [{"id": f"page{i}", "title": f"Page {i}", "path": f"section/page-{i}"} for i in range(10)]})

        cache = DocumentationCache(gitbook_client=client)
        await cache.refresh()

        # Limit to 5 results
        resources = await cache.list_resources(limit=5)

        assert len(resources) == 5

    @pytest.mark.asyncio
    async def test_list_resources_combined_filters(self):
        """Test combining multiple filters"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(
            return_value={
                "pages": [
                    {"id": "page1", "title": "Billing API", "path": "developer-resources/rest-api/billing"},
                    {"id": "page2", "title": "Orders API", "path": "developer-resources/rest-api/orders"},
                    {"id": "page3", "title": "Billing FAQ", "path": "help-and-support/faqs/billing"},
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
    async def test_get_documentation_index(self):
        """Test getting documentation index/hierarchy"""
        client = Mock(spec=GitBookClient)
        client.fetch_space_content = AsyncMock(
            return_value={
                "pages": [
                    {"id": "page1", "title": "Orders API", "path": "developer-resources/rest-api/orders"},
                    {"id": "page2", "title": "Billing API", "path": "developer-resources/rest-api/billing"},
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
    async def test_get_resource_success(self, mock_gitbook_client):
        """Test getting a specific resource"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)
        await cache.refresh()

        content = await cache.get_resource("docs://getting-started")

        assert content is not None
        assert "Getting Started" in content

    @pytest.mark.asyncio
    async def test_get_resource_not_found(self, mock_gitbook_client):
        """Test getting a non-existent resource"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)
        await cache.refresh()

        content = await cache.get_resource("docs://non-existent")

        assert content is None

    @pytest.mark.asyncio
    async def test_ensure_cached_refreshes_if_needed(self, mock_gitbook_client):
        """Test ensure_cached refreshes when needed"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)

        # Cache is empty, should trigger refresh
        await cache.ensure_cached()

        assert cache._content is not None
        assert mock_gitbook_client.fetch_space_content.called

    def test_get_cache_info(self, mock_gitbook_client):
        """Test getting cache information"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)

        info = cache.get_cache_info()

        assert info["enabled"] is True
        assert info["has_content"] is False
        assert info["needs_refresh"] is True
        assert info["resource_count"] == 0
        assert info["refresh_interval_hours"] == 24

    @pytest.mark.asyncio
    async def test_refresh_interval_check(self, mock_gitbook_client):
        """Test cache respects refresh interval"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client, refresh_interval_hours=1)

        # First refresh
        await cache.refresh()
        assert cache.needs_refresh is False

        # Simulate time passing (more than refresh interval)
        cache._last_refresh = datetime.now() - timedelta(hours=2)
        assert cache.needs_refresh is True

    def test_extract_text_from_document(self, mock_gitbook_client):
        """Test extracting text from GitBook document structure"""
        cache = DocumentationCache(gitbook_client=mock_gitbook_client)

        document = {
            "nodes": [
                {"type": "paragraph", "nodes": [{"object": "text", "leaves": [{"text": "Header text"}]}]},
                {"type": "paragraph", "nodes": [{"object": "text", "leaves": [{"text": "Paragraph 1"}]}]},
                {
                    "type": "paragraph",
                    "nodes": [{"object": "text", "leaves": [{"text": "Paragraph 2"}]}, {"text": "Nested text"}],
                },
            ]
        }

        text = cache._extract_text_from_document(document)

        assert "Header text" in text
        assert "Paragraph 1" in text
        assert "Paragraph 2" in text
        assert "Nested text" in text


class TestGitBookConfigIntegration:
    """Test GitBook configuration integration"""

    def test_config_has_gitbook_settings(self):
        """Test config includes GitBook settings"""
        from src.config import config

        # These should exist even if empty
        assert hasattr(config, "gitbook_api_key")
        assert hasattr(config, "gitbook_space_id")
        assert hasattr(config, "gitbook_api_base_url")
        assert hasattr(config, "gitbook_cache_refresh_hours")

    def test_config_default_values(self):
        """Test config has correct default values"""
        from src.config import config

        # Default base URL should be GitBook API v1
        assert config.gitbook_api_base_url == "https://api.gitbook.com/v1"
        # Default refresh should be 24 hours
        assert config.gitbook_cache_refresh_hours == 24
