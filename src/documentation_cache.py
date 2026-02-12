from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from .gitbook_client import GitBookClient

logger = logging.getLogger(__name__)


class DocumentationCache:
    """
    Manages cached documentation from GitBook with automatic TTL-based refresh
    """

    def __init__(self, gitbook_client: GitBookClient | None = None, refresh_interval_hours: int = 24, public_url: str = ""):
        """
        Initialize documentation cache

        Args:
            gitbook_client: GitBook client instance (None disables caching)
            refresh_interval_hours: Hours between cache refreshes
            public_url: Public URL where documentation is published (for browser links)
        """
        self.gitbook_client = gitbook_client
        self.refresh_interval = timedelta(hours=refresh_interval_hours)
        self.public_url = public_url.rstrip("/") if public_url else ""

        self._content: dict[str, Any] | None = None
        self._last_refresh: datetime | None = None
        self._refresh_task: asyncio.Task | None = None
        self._is_refreshing = False

        self._resources: dict[str, dict[str, Any]] = {}

        if gitbook_client:
            logger.info(f"📚 Documentation cache initialized (refresh interval: {refresh_interval_hours}h)")
        else:
            logger.info("📚 Documentation cache disabled (no GitBook client configured)")

    @property
    def is_enabled(self) -> bool:
        """Check if documentation cache is enabled"""
        return self.gitbook_client is not None

    @property
    def needs_refresh(self) -> bool:
        """Check if cache needs refresh"""
        if not self.is_enabled:
            return False

        if self._content is None or self._last_refresh is None:
            return True

        return datetime.now() - self._last_refresh > self.refresh_interval

    async def refresh(self, force: bool = False) -> bool:
        """
        Refresh the documentation cache

        Args:
            force: Force refresh even if cache is still valid

        Returns:
            True if refresh was successful, False otherwise
        """
        if not self.is_enabled:
            logger.warning("📚 Documentation cache is disabled, skipping refresh")
            return False

        if self._is_refreshing:
            logger.info("📚 Refresh already in progress, skipping")
            return False

        if not force and not self.needs_refresh:
            logger.info("📚 Cache is still valid, skipping refresh")
            return True

        try:
            self._is_refreshing = True
            logger.info("📚 Refreshing documentation cache...")

            content = await self.gitbook_client.fetch_space_content()

            self._content = content
            self._last_refresh = datetime.now()

            self._build_resource_index()

            logger.info(f"✅ Documentation cache refreshed successfully ({len(self._resources)} resources)")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to refresh documentation cache: {e}")
            return False
        finally:
            self._is_refreshing = False

    def _build_resource_index(self):
        """Build an index of resources from the content for fast lookups"""
        self._resources.clear()

        if not self._content:
            return

        def index_page(page):
            """Recursively index a page and its children"""
            if not isinstance(page, dict):
                return

            page_id = page.get("id")
            page_path = page.get("path", "")
            title = page.get("title", "Untitled")

            if page_id:
                uri = f"docs://{page_path}" if page_path else f"docs://page-{page_id}"

                metadata = {
                    "id": page_id,
                    "path": page_path,
                    "title": title,
                }

                if self.public_url and page_path:
                    metadata["browser_url"] = f"{self.public_url}/{page_path}"

                self._resources[uri] = {
                    "uri": uri,
                    "name": title,
                    "description": f"Documentation page: {title}",
                    "mimeType": "text/markdown",
                    "metadata": metadata,
                    "content": None,  # Content will be fetched on-demand
                }

            pages = page.get("pages", [])
            if isinstance(pages, list):
                for child_page in pages:
                    index_page(child_page)

        pages = self._content.get("pages", [])
        if isinstance(pages, list):
            for page in pages:
                index_page(page)

        logger.info(f"📇 Built resource index with {len(self._resources)} entries")

    async def ensure_cached(self):
        """Ensure cache is populated, refresh if needed"""
        if not self.is_enabled:
            return

        if self.needs_refresh:
            await self.refresh()

    async def get_content(self) -> dict[str, Any] | None:
        """
        Get cached content, refreshing if necessary

        Returns:
            Cached content dictionary or None if unavailable
        """
        await self.ensure_cached()
        return self._content

    async def list_resources(
        self,
        section: str | None = None,
        subsection: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        List available documentation resources with optional filtering

        Args:
            section: Filter by top-level section (e.g., "developer-resources")
            subsection: Filter by subsection (e.g., "rest-api")
            search: Search keyword in title and path (case-insensitive)
            limit: Maximum number of results to return

        Returns:
            List of resource metadata dictionaries
        """
        await self.ensure_cached()
        resources = list(self._resources.values())

        if section:
            resources = [r for r in resources if r["uri"].startswith(f"docs://{section}/")]

        if subsection:
            if section:
                prefix = f"docs://{section}/{subsection}/"
            else:
                prefix = f"/{subsection}/"
            resources = [r for r in resources if prefix in r["uri"]]

        if search:
            search_lower = search.lower()
            resources = [r for r in resources if search_lower in r["name"].lower() or search_lower in r["uri"].lower()]

        if limit and limit > 0:
            resources = resources[:limit]

        return resources

    async def get_resource(self, uri: str) -> str | None:
        """
        Get content for a specific resource (lazy-loaded and cached)

        Args:
            uri: Resource URI (e.g., "docs://getting-started/authentication")

        Returns:
            Resource content as string, or None if not found
        """
        await self.ensure_cached()

        if uri not in self._resources:
            logger.warning(f"📚 Resource not found: {uri}")
            return None

        resource = self._resources[uri]

        if resource.get("content") is not None:
            return resource["content"]

        # Fetch on-demand using page ID (more reliable than path)
        page_id = resource["metadata"].get("id")

        if not page_id:
            logger.error(f"📚 Resource has no ID: {uri}")
            return "Content not available - no page ID"

        try:
            page_data = await self.gitbook_client.fetch_page_by_id(page_id)

            markdown = page_data.get("markdown", "")

            available_fields = list(page_data.keys())
            logger.debug(f"📋 GitBook page fields: {available_fields}")

            if not markdown and "document" in page_data:
                logger.debug("📄 No markdown, extracting from document structure")
                markdown = self._extract_text_from_document(page_data["document"])

            resource["content"] = markdown or "No content available"

            content_length = len(markdown) if markdown else 0
            logger.info(f"✅ Fetched and cached content for: {uri} (length: {content_length})")

            return resource["content"]

        except Exception as e:
            logger.error(f"❌ Failed to fetch resource {uri}: {e}")
            return f"Error fetching content: {str(e)}"

    def _extract_text_from_document(self, document: dict) -> str:
        """
        Extract text from GitBook document structure

        GitBook uses a nested structure: document -> nodes -> (blocks or text) -> leaves -> text

        Args:
            document: GitBook document structure

        Returns:
            Extracted text content
        """
        text_parts = []

        def extract_from_node(node):
            """Recursively extract text from a node"""
            if not isinstance(node, dict):
                return

            if node.get("object") == "text" and "leaves" in node:
                for leaf in node["leaves"]:
                    if isinstance(leaf, dict) and "text" in leaf:
                        text_parts.append(leaf["text"])

            if "text" in node:
                text_parts.append(node["text"])

            if "nodes" in node and isinstance(node["nodes"], list):
                for child in node["nodes"]:
                    extract_from_node(child)

                if node.get("type") in [
                    "paragraph",
                    "heading-1",
                    "heading-2",
                    "heading-3",
                    "heading-4",
                    "heading-5",
                    "heading-6",
                    "list-item",
                ]:
                    text_parts.append("\n")

        if "nodes" in document:
            for node in document["nodes"]:
                extract_from_node(node)

        content = "".join(text_parts)
        while "\n\n\n" in content:
            content = content.replace("\n\n\n", "\n\n")

        return content.strip()

    async def get_documentation_index(self) -> dict[str, Any]:
        """
        Get the documentation structure/hierarchy (table of contents)

        Returns:
            Dictionary containing sections, subsections, and page counts
        """
        await self.ensure_cached()

        from collections import defaultdict

        sections = defaultdict(lambda: {"subsections": defaultdict(int), "total": 0})

        for uri in self._resources:
            path = uri.replace("docs://", "")
            parts = path.split("/")

            if len(parts) >= 1:
                section = parts[0]
                sections[section]["total"] += 1

                if len(parts) >= 2:
                    subsection = parts[1]
                    sections[section]["subsections"][subsection] += 1

        result = {"total_pages": len(self._resources), "sections": []}

        for section_name in sorted(sections.keys()):
            section_data = sections[section_name]
            subsections_list = [{"name": sub_name, "pages": count} for sub_name, count in sorted(section_data["subsections"].items())]

            result["sections"].append({"name": section_name, "total_pages": section_data["total"], "subsections": subsections_list})

        return result

    def get_cache_info(self) -> dict[str, Any]:
        """
        Get information about the cache state

        Returns:
            Dictionary with cache statistics
        """
        return {
            "enabled": self.is_enabled,
            "has_content": self._content is not None,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "needs_refresh": self.needs_refresh,
            "resource_count": len(self._resources),
            "refresh_interval_hours": self.refresh_interval.total_seconds() / 3600,
            "is_refreshing": self._is_refreshing,
        }
