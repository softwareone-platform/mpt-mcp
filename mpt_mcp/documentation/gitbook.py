import asyncio
import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default max concurrent requests to GitBook API (avoids 429 rate limits)
DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_MAX_CONCURRENT_REQUESTS = 2
DEFAULT_REQUEST_TIMEOUT = 30.0
# Errors of a GitBook request: HTTP and network errors, the timeout of its last retry and a
# response body that is not JSON
GITBOOK_REQUEST_ERRORS = (httpx.HTTPError, TimeoutError, ValueError)


@dataclass(frozen=True)
class RetryPolicy:
    """When to retry a GitBook request and how long to wait before each retry."""

    backoff_base: float = 1.0
    backoff_factor: float = 2.0
    max_attempts: int = 3
    status_codes: frozenset[int] = frozenset((
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.SERVICE_UNAVAILABLE,
    ))

    def delay(self, attempt: int, retry_after: str | None = None) -> float:
        """
        Get the seconds to wait before retrying a request.

        Args:
            attempt: Number of the attempt that failed, from 1
            retry_after: Retry-After header of the response, if any

        Returns:
            The Retry-After seconds when they are a number, otherwise an exponential backoff
        """
        if retry_after and retry_after.isdigit():
            return float(retry_after)

        return self.backoff_base * self.backoff_factor ** (attempt - 1)


DEFAULT_RETRY_POLICY = RetryPolicy()


class GitBookClient:
    """Client for fetching content from GitBook API v1."""

    def __init__(
        self,
        api_key: str,
        space_id: str,
        base_url: str = "https://api.gitbook.com/v1",
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ):
        """
        Initialize GitBook API client.

        Args:
            api_key: GitBook API token for authentication
            space_id: The GitBook space ID to fetch content from
            base_url: Base URL for GitBook API (default: https://api.gitbook.com/v1)
            max_concurrent_requests: Max concurrent API requests (default 2, helps avoid 429)
            retry_policy: When to retry a request and how long to wait (default 3 attempts)
        """
        self.api_key = api_key
        self.space_id = space_id
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        self._retry_policy = retry_policy
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

        logger.info(
            "GitBook client initialized for space: %s (max concurrent: %s)",
            space_id,
            max_concurrent_requests,
        )

    async def fetch_page_by_id(self, page_id: str) -> dict[str, Any]:
        """
        Fetch a specific page by its ID.

        Args:
            page_id: The page ID (e.g., "abc123def456")

        Returns:
            Dictionary containing page content

        Raises:
            httpx.HTTPError: If the request fails
        """
        url = f"{self.base_url}/spaces/{self.space_id}/content/page/{page_id}"
        logger.debug("Fetching page by ID: %s", page_id)
        return await self._get_with_retry(url)

    async def fetch_page_by_path(self, page_path: str) -> dict[str, Any]:
        """
        Fetch a specific page by its path.

        Args:
            page_path: The page path (e.g., "getting-started/authentication")

        Returns:
            Dictionary containing page content

        Raises:
            httpx.HTTPError: If the request fails
        """
        page_path = page_path.lstrip("/")
        url = f"{self.base_url}/spaces/{self.space_id}/content/path/{page_path}"
        logger.debug("Fetching page: %s", page_path)
        return await self._get_with_retry(url)

    async def fetch_space_content(self) -> dict[str, Any]:
        """
        Fetch all content from the GitBook space.

        This includes pages, files, and other content items.

        Returns:
            Dictionary containing all space content

        Raises:
            httpx.HTTPError: If the request fails
        """
        url = f"{self.base_url}/spaces/{self.space_id}/content"
        logger.info("Fetching GitBook space content from: %s", url)

        space_content = await self._get_with_retry(url)
        logger.info("Successfully fetched GitBook content")
        pages = space_content.get("pages")
        if pages is not None:
            page_count = len(pages) if isinstance(pages, list) else "unknown"
            logger.info("Pages: %s", page_count)
        return space_content

    async def validate_credentials(self) -> bool:
        """
        Validate that the API credentials are valid.

        Returns:
            True if credentials are valid, False otherwise
        """
        url = f"{self.base_url}/spaces/{self.space_id}"
        try:
            await self._get_with_retry(url)
        except GITBOOK_REQUEST_ERRORS:
            logger.exception("GitBook credential validation failed")
            return False

        logger.info("GitBook credentials validated successfully")
        return True

    async def _get_attempt(self, url: str, attempt: int) -> dict[str, Any]:
        try:
            async with (
                asyncio.timeout(DEFAULT_REQUEST_TIMEOUT),
                httpx.AsyncClient(
                    follow_redirects=True,
                    http2=True,
                    timeout=httpx.Timeout(DEFAULT_REQUEST_TIMEOUT, connect=DEFAULT_CONNECT_TIMEOUT),
                ) as client,
            ):
                response = await client.get(url, headers=self._headers)
        except TimeoutError:
            if attempt == self._retry_policy.max_attempts:
                raise

            reason, delay = "timeout", self._retry_policy.delay(attempt)
        else:
            if (
                response.status_code not in self._retry_policy.status_codes
                or attempt == self._retry_policy.max_attempts
            ):
                response.raise_for_status()
                page: dict[str, Any] = response.json()
                return page

            reason, delay = (
                str(response.status_code),
                self._retry_policy.delay(attempt, response.headers.get("Retry-After")),
            )
        logger.warning(
            "GitBook request failed (%s), retry in %.1fs (attempt %s/%s)",
            reason,
            delay,
            attempt,
            self._retry_policy.max_attempts,
        )
        await asyncio.sleep(delay)
        return await self._get_attempt(url, attempt + 1)

    async def _get_with_retry(self, url: str) -> dict[str, Any]:
        # Held while waiting to retry too, so retries never exceed max_concurrent_requests
        async with self._semaphore:
            return await self._get_attempt(url, attempt=1)
