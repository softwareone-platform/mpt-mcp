import logging
from typing import Any
from urllib.parse import urlencode, urlparse

import anyio
import httpx

logger = logging.getLogger(__name__)

BEARER_PREFIX = "Bearer "
DEFAULT_CONNECT_TIMEOUT = 30.0


def normalize_endpoint_url(endpoint: str) -> str:
    """
    Normalize a Marketplace API endpoint to its base URL.

    Every path is dropped, because the paths of the OpenAPI spec already start with /public/v1.

    Args:
        endpoint: Endpoint, e.g. https://api.s1.show/public/v1

    Returns:
        scheme://hostname[:port], e.g. https://api.s1.show, or the endpoint unchanged when it has
        no scheme and host
    """
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return endpoint

    return f"{parsed.scheme}://{parsed.netloc}"


class APIClient:
    """Client for making authenticated requests to the SoftwareOne Marketplace API."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        """
        Initialize the API client.

        Args:
            base_url: Base URL of the marketplace API (any path will be stripped)
            token: Authentication token (with or without "Bearer" prefix)
            timeout: Default request timeout in seconds
        """
        # Paths come from the OpenAPI spec, so keep only scheme://hostname[:port]
        normalized_base_url = normalize_endpoint_url(base_url)
        if base_url != normalized_base_url:
            logger.info(
                "Base URL normalization: Stripped path from '%s' → '%s' (paths come from "
                "OpenAPI spec)",
                base_url,
                normalized_base_url,
            )

        self.base_url = normalized_base_url

        if token.startswith(BEARER_PREFIX):
            self.token = token
        elif token:
            self.token = f"{BEARER_PREFIX}{token}"
        else:
            self.token = BEARER_PREFIX

        self.user_id = self._extract_user_id(token)
        if self.user_id:
            logger.info("Authenticated as user: %s", self.user_id)

        self.timeout = timeout

    async def get(  # noqa: WPS210
        self,
        endpoint: str,
        query_params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Make a GET request to the API.

        Args:
            endpoint: API endpoint path (e.g., "/products" or "/products/{id}")
            query_params: Query parameters dictionary. Special handling for 'rql' key:
                   - If 'rql' key exists, its value becomes the raw query string directly after '?'
                   - Example: {"rql": "eq(status,Failed)"} → /endpoint?eq(status,Failed)
                   - NOT sent as ?rql=... (it's not a query parameter, it IS the query string)
                   - Other params in the dict are added as normal query parameters

        Returns:
            JSON response from the API

        Raises:
            httpx.HTTPError: If the request fails
            httpx.TimeoutException: If the request times out
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        # RQL is the query string itself: {"rql": "eq(status,Failed)"} is sent as
        # /endpoint?eq(status,Failed), not /endpoint?rql=eq(status,Failed)
        if query_params and "rql" in query_params:
            rql_query = query_params.pop("rql")
            query_parts = [rql_query]

            if query_params:
                additional_query = urlencode(query_params, doseq=True)
                query_parts.append(additional_query)

            query_string = "&".join(query_parts)
            url = f"{url}?{query_string}"
            query_params = None

        logger.info("Marketplace API request: %s", httpx.URL(url, params=query_params))

        timeout_config = httpx.Timeout(self.timeout, connect=DEFAULT_CONNECT_TIMEOUT)
        async with httpx.AsyncClient(
            follow_redirects=True, http2=True, timeout=timeout_config
        ) as client:
            try:
                with anyio.fail_after(self.timeout):
                    response = await client.get(url, params=query_params, headers=headers)
                    response.raise_for_status()
                    response_data = response.json()
            except TimeoutError as error:
                raise httpx.TimeoutException(
                    f"Request timed out after {self.timeout} seconds"
                ) from error

            logger.info(
                "Marketplace API response %s: %s",
                response.status_code,
                self._describe_response(response_data),
            )

            return response_data

    def _describe_response(self, response_data: Any) -> str:
        """
        Summarize a response for the log in one line.

        Args:
            response_data: Parsed JSON response

        Returns:
            Items returned, pagination and omitted fields, e.g. "items=10, offset=0, limit=10,
            total=45"
        """
        if isinstance(response_data, list):
            return f"items={len(response_data)}"

        if not isinstance(response_data, dict):
            return type(response_data).__name__

        details = []
        data = response_data.get("data")
        if isinstance(data, list):
            details.append(f"items={len(data)}")
        elif isinstance(data, dict) or "data" not in response_data:
            details.append("single item")
        meta = response_data.get("$meta")
        meta = meta if isinstance(meta, dict) else {}
        pagination = meta.get("pagination") or response_data.get("pagination")
        if isinstance(pagination, dict):
            details.append(
                f"offset={pagination.get('offset')}, limit={pagination.get('limit')}, "
                f"total={pagination.get('total')}"
            )
        if meta.get("omitted"):
            omitted_fields = ", ".join(meta["omitted"])
            details.append(f"omitted fields: {omitted_fields}")
        return ", ".join(details)

    def _extract_user_id(self, token: str) -> str | None:
        """
        Extract user identifier from token.

        Token format: idt:TKN-XXXX-XXXX:actual_token
        Returns: TKN-XXXX-XXXX (the user identifier)

        Args:
            token: The authentication token (with or without Bearer prefix)

        Returns:
            User identifier (TKN-XXXX-XXXX) or None if not found
        """
        token_value = token.replace(BEARER_PREFIX, "").strip()

        if token_value.startswith("idt:") and token_value.count(":") >= 2:
            parts = token_value.split(":")
            if len(parts) >= 3 and parts[1].startswith("TKN-"):
                return parts[1]

        return None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
