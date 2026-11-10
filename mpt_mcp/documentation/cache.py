from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from mpt_mcp.documentation.gitbook import GITBOOK_REQUEST_ERRORS

if TYPE_CHECKING:
    from mpt_mcp.documentation.gitbook import GitBookClient

logger = logging.getLogger(__name__)


class DocumentationCache:
    """Manages cached documentation from GitBook with automatic TTL-based refresh."""

    def __init__(
        self,
        gitbook_client: GitBookClient | None = None,
        refresh_interval_hours: int = 24,
        public_url: str = "",
    ):
        """
        Initialize documentation cache.

        Args:
            gitbook_client: GitBook client instance (None disables caching)
            refresh_interval_hours: Hours between cache refreshes
            public_url: Public URL where documentation is published (for browser links)
        """
        self.gitbook_client = gitbook_client
        self.refresh_interval = dt.timedelta(hours=refresh_interval_hours)
        self.public_url = public_url.rstrip("/") if public_url else ""

        self._space_content: dict[str, Any] | None = None
        self._last_refresh: dt.datetime | None = None
        self._is_refreshing = False

        self._resources: dict[str, dict[str, Any]] = {}

        if gitbook_client:
            logger.info(
                "Documentation cache initialized (refresh interval: %sh)", refresh_interval_hours
            )
        else:
            logger.info("Documentation cache disabled (no GitBook client configured)")

    @property
    def is_enabled(self) -> bool:
        """Check if documentation cache is enabled"""
        return self.gitbook_client is not None

    @property
    def needs_refresh(self) -> bool:
        """Check if cache needs refresh"""
        if not self.is_enabled:
            return False

        if self._space_content is None or self._last_refresh is None:
            return True

        return dt.datetime.now(dt.UTC) - self._last_refresh > self.refresh_interval

    async def ensure_cached(self) -> None:
        """Ensure cache is populated, refresh if needed."""
        if not self.is_enabled:
            return

        if self.needs_refresh:
            await self.refresh()

    def get_cache_info(self) -> dict[str, Any]:
        """
        Get information about the cache state.

        Returns:
            Dictionary with cache statistics
        """
        return {
            "enabled": self.is_enabled,
            "has_content": self._space_content is not None,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "needs_refresh": self.needs_refresh,
            "resource_count": len(self._resources),
            "refresh_interval_hours": self.refresh_interval / dt.timedelta(hours=1),
            "is_refreshing": self._is_refreshing,
        }

    async def get_documentation_index(self) -> dict[str, Any]:
        """
        Get the documentation structure/hierarchy (table of contents).

        Returns:
            Dictionary containing sections, subsections, and page counts
        """
        await self.ensure_cached()

        sections: defaultdict[str, dict[str, Any]] = defaultdict(
            lambda: {"subsections": defaultdict(int), "total": 0}
        )

        for uri in self._resources:
            path = uri.replace("docs://", "")
            parts = path.split("/")

            if len(parts) >= 1:
                section = parts[0]
                sections[section]["total"] += 1

                if len(parts) >= 2:
                    subsection = parts[1]
                    sections[section]["subsections"][subsection] += 1

        result: dict[str, Any] = {"total_pages": len(self._resources), "sections": []}

        for section_name in sorted(sections.keys()):
            section_data = sections[section_name]
            subsections_list = [
                {"name": sub_name, "pages": count}
                for sub_name, count in sorted(section_data["subsections"].items())
            ]

            result["sections"].append({
                "name": section_name,
                "total_pages": section_data["total"],
                "subsections": subsections_list,
            })

        return result

    async def get_resource(self, uri: str) -> str | None:
        """
        Get content for a specific resource (lazy-loaded and cached).

        Args:
            uri: Resource URI (e.g., "docs://getting-started/authentication")

        Returns:
            Resource content as string, or None if not found
        """
        await self.ensure_cached()

        if uri not in self._resources:
            logger.warning("Resource not found: %s", uri)
            return None

        resource = self._resources[uri]

        cached_content: str | None = resource.get("content")
        if cached_content is not None:
            return cached_content

        # Fetch on-demand using page ID (more reliable than path)
        page_id = resource["metadata"].get("id")

        if not page_id:
            logger.error("Resource has no ID: %s", uri)
            return "Content not available - no page ID"

        if self.gitbook_client is None:
            return None

        try:
            page_data = await self.gitbook_client.fetch_page_by_id(page_id)
        except GITBOOK_REQUEST_ERRORS as error:
            logger.exception("Failed to fetch resource %s", uri)
            return f"Error fetching content: {error!s}"

        logger.debug("GitBook page fields: %s", list(page_data.keys()))
        markdown = page_data.get("markdown", "")
        if not markdown and "document" in page_data:
            logger.debug("No markdown, extracting from document structure")
            markdown = self._extract_text_from_document(page_data["document"])

        fetched_content: str = markdown or "No content available"
        resource["content"] = fetched_content
        logger.info("Fetched and cached content for: %s (length: %s)", uri, len(markdown or ""))
        return fetched_content

    async def list_resources(
        self,
        section: str | None = None,
        subsection: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        List available documentation resources with optional filtering.

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
            resources = [
                resource
                for resource in resources
                if resource["uri"].startswith(f"docs://{section}/")
            ]

        if subsection:
            prefix = f"docs://{section}/{subsection}/" if section else f"/{subsection}/"
            resources = [resource for resource in resources if prefix in resource["uri"]]

        if search:
            search_lower = search.lower()
            resources = [
                resource
                for resource in resources
                if search_lower in resource["name"].lower()
                or search_lower in resource["uri"].lower()
            ]

        if limit and limit > 0:
            resources = resources[:limit]

        return resources

    async def refresh(self, *, force: bool = False) -> bool:
        """
        Refresh the documentation cache.

        Args:
            force: Force refresh even if cache is still valid

        Returns:
            True if refresh was successful, False otherwise
        """
        if self.gitbook_client is None:
            logger.warning("Documentation cache is disabled, skipping refresh")
            return False

        if self._is_refreshing:
            logger.info("Refresh already in progress, skipping")
            return False

        if not force and not self.needs_refresh:
            logger.info("Cache is still valid, skipping refresh")
            return True

        self._is_refreshing = True
        logger.info("Refreshing documentation cache...")
        try:
            space_content = await self.gitbook_client.fetch_space_content()
        except GITBOOK_REQUEST_ERRORS:
            logger.exception("Failed to refresh documentation cache")
            return False
        else:
            self._space_content = space_content
            self._last_refresh = dt.datetime.now(dt.UTC)
            self._build_resource_index()
            logger.info(
                "Documentation cache refreshed successfully (%s resources)", len(self._resources)
            )
            return True
        finally:
            self._is_refreshing = False

    def _build_resource_index(self) -> None:
        self._resources.clear()

        if not self._space_content:
            return

        pages = self._space_content.get("pages", [])
        if isinstance(pages, list):
            for page in pages:
                self._index_page(page)

        logger.info("Built resource index with %s entries", len(self._resources))

    def _extract_from_node(self, node: Any, text_parts: list[str]) -> None:
        if not isinstance(node, dict):
            return

        leaves = node.get("leaves")
        if node.get("object") == "text" and leaves is not None:
            text_leaves = [leaf for leaf in leaves if isinstance(leaf, dict) and "text" in leaf]
            text_parts.extend(leaf["text"] for leaf in text_leaves)

        text = node.get("text")
        if text is not None:
            text_parts.append(text)

        children = node.get("nodes")
        if isinstance(children, list):
            for child in children:
                self._extract_from_node(child, text_parts)

            if node.get("type") in {
                "paragraph",
                "heading-1",
                "heading-2",
                "heading-3",
                "heading-4",
                "heading-5",
                "heading-6",
                "list-item",
            }:
                text_parts.append("\n")

    def _extract_text_from_document(self, document: dict[str, Any]) -> str:
        # GitBook nests the text: document -> nodes -> (blocks or text) -> leaves -> text
        text_parts: list[str] = []

        for node in document.get("nodes", ()):
            self._extract_from_node(node, text_parts)

        text = "".join(text_parts)
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")

        return text.strip()

    def _index_page(self, page: Any) -> None:
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
                "content": None,
            }

        pages = page.get("pages", [])
        if isinstance(pages, list):
            for child_page in pages:
                self._index_page(child_page)
