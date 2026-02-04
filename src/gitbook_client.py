"""
GitBook API client for fetching documentation content
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitBookClient:
    """Client for fetching content from GitBook API v1"""

    def __init__(self, api_key: str, space_id: str, base_url: str = "https://api.gitbook.com/v1"):
        """
        Initialize GitBook API client

        Args:
            api_key: GitBook API token for authentication
            space_id: The GitBook space ID to fetch content from
            base_url: Base URL for GitBook API (default: https://api.gitbook.com/v1)
        """
        self.api_key = api_key
        self.space_id = space_id
        self.base_url = base_url.rstrip("/")

        logger.info(f"📚 GitBook client initialized for space: {space_id}")

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def fetch_space_content(self, timeout: float = 30.0) -> dict[str, Any]:
        """
        Fetch all content from the GitBook space

        This includes pages, files, and other content items.

        Args:
            timeout: Request timeout in seconds

        Returns:
            Dictionary containing all space content

        Raises:
            httpx.HTTPError: If the request fails
        """
        url = f"{self.base_url}/spaces/{self.space_id}/content"
        headers = self._get_headers()

        logger.info(f"📥 Fetching GitBook space content from: {url}")

        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            response = await client.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            content = response.json()

            logger.info("✅ Successfully fetched GitBook content")

            # Log some stats
            if "pages" in content:
                page_count = len(content["pages"]) if isinstance(content["pages"], list) else "unknown"
                logger.info(f"   📄 Pages: {page_count}")

            return content

    async def fetch_page_by_path(self, page_path: str, timeout: float = 30.0) -> dict[str, Any]:
        """
        Fetch a specific page by its path

        Args:
            page_path: The page path (e.g., "getting-started/authentication")
            timeout: Request timeout in seconds

        Returns:
            Dictionary containing page content

        Raises:
            httpx.HTTPError: If the request fails
        """
        # Remove leading slash if present
        page_path = page_path.lstrip("/")

        url = f"{self.base_url}/spaces/{self.space_id}/content/path/{page_path}"
        headers = self._get_headers()

        logger.debug(f"📥 Fetching page: {page_path}")

        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            response = await client.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()

    async def fetch_page_by_id(self, page_id: str, timeout: float = 30.0) -> dict[str, Any]:
        """
        Fetch a specific page by its ID

        Args:
            page_id: The page ID (e.g., "abc123def456")
            timeout: Request timeout in seconds

        Returns:
            Dictionary containing page content

        Raises:
            httpx.HTTPError: If the request fails
        """
        url = f"{self.base_url}/spaces/{self.space_id}/content/page/{page_id}"
        headers = self._get_headers()

        logger.debug(f"📥 Fetching page by ID: {page_id}")

        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            response = await client.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()

    async def validate_credentials(self) -> bool:
        """
        Validate that the API credentials are valid

        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            url = f"{self.base_url}/spaces/{self.space_id}"
            headers = self._get_headers()

            async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                response.raise_for_status()

            logger.info("✅ GitBook credentials validated successfully")
            return True
        except Exception as e:
            logger.error(f"❌ GitBook credential validation failed: {e}")
            return False
