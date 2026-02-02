"""
GitBook API client for fetching documentation content.

Uses a semaphore to limit concurrent API requests and retries on 429 (rate limit)
with exponential backoff to avoid overwhelming the GitBook API.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default max concurrent requests to GitBook API (avoids 429 rate limits)
DEFAULT_MAX_CONCURRENT_REQUESTS = 2
# Max retries on 429/503
MAX_RETRIES = 3
# Base delay in seconds for exponential backoff when Retry-After is not present
RETRY_BACKOFF_BASE_SEC = 1.0


class GitBookClient:
    """Client for fetching content from GitBook API v1"""

    def __init__(
        self,
        api_key: str,
        space_id: str,
        base_url: str = "https://api.gitbook.com/v1",
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    ):
        """
        Initialize GitBook API client

        Args:
            api_key: GitBook API token for authentication
            space_id: The GitBook space ID to fetch content from
            base_url: Base URL for GitBook API (default: https://api.gitbook.com/v1)
            max_concurrent_requests: Max concurrent API requests (default 2, helps avoid 429)
        """
        self.api_key = api_key
        self.space_id = space_id
        self.base_url = base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

        logger.info(f"📚 GitBook client initialized for space: {space_id} (max concurrent: {max_concurrent_requests})")

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def _get_with_retry(self, url: str, timeout: float = 30.0) -> dict[str, Any]:
        """
        Perform a GET request with concurrency limit and retry on 429/503.

        Acquires the semaphore so we never exceed max_concurrent_requests.
        On 429 (rate limit) or 503 (unavailable), retries with backoff.
        """
        async with self._semaphore:
            for attempt in range(MAX_RETRIES):
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    response = await client.get(url, headers=self._get_headers(), timeout=timeout)
                if response.status_code in (429, 503):
                    if attempt < MAX_RETRIES - 1:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            wait_sec = float(retry_after)
                        else:
                            wait_sec = RETRY_BACKOFF_BASE_SEC * (2**attempt)
                        logger.warning(f"📚 GitBook rate limit/unavailable ({response.status_code}), retry in {wait_sec:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                        await asyncio.sleep(wait_sec)
                        continue
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            raise RuntimeError("Unexpected retry loop exit")

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
        logger.info(f"📥 Fetching GitBook space content from: {url}")

        content = await self._get_with_retry(url, timeout=timeout)
        logger.info("✅ Successfully fetched GitBook content")
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
        page_path = page_path.lstrip("/")
        url = f"{self.base_url}/spaces/{self.space_id}/content/path/{page_path}"
        logger.debug(f"📥 Fetching page: {page_path}")
        return await self._get_with_retry(url, timeout=timeout)

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
        logger.debug(f"📥 Fetching page by ID: {page_id}")
        return await self._get_with_retry(url, timeout=timeout)

    async def validate_credentials(self) -> bool:
        """
        Validate that the API credentials are valid

        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            url = f"{self.base_url}/spaces/{self.space_id}"
            await self._get_with_retry(url, timeout=10.0)
            logger.info("✅ GitBook credentials validated successfully")
            return True
        except Exception as e:
            logger.error(f"❌ GitBook credential validation failed: {e}")
            return False
