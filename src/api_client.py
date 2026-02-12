import logging
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

BEARER_PREFIX = "Bearer "


class APIClient:
    """Client for making authenticated requests to the SoftwareOne Marketplace API"""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        """
        Initialize the API client

        Args:
            base_url: Base URL of the marketplace API (any path will be stripped)
            token: Authentication token (with or without "Bearer" prefix)
            timeout: Default request timeout in seconds
        """
        # Normalize the base URL to only scheme://hostname[:port]
        # This prevents path duplication when OpenAPI paths are absolute
        # Examples:
        #   https://api.s1.show/public -> https://api.s1.show
        #   https://api.s1.show/v1 -> https://api.s1.show
        #   https://api.s1.show/ -> https://api.s1.show
        parsed = urlparse(base_url)
        normalized_base_url = f"{parsed.scheme}://{parsed.netloc}"

        if base_url != normalized_base_url:
            logger.info(f"🔧 Base URL normalization: Stripped path from '{base_url}' → '{normalized_base_url}' (paths come from OpenAPI spec)")

        self.base_url = normalized_base_url

        # Normalize token - ensure it has "Bearer" prefix
        # Handle both formats: "Bearer token" and "token"
        if not token:
            self.token = BEARER_PREFIX
        elif token.startswith(BEARER_PREFIX):
            self.token = token
        else:
            self.token = f"{BEARER_PREFIX}{token}"

        # Extract user identifier from token (if present)
        # Token format: idt:TKN-XXXX-XXXX:actual_token
        self.user_id = self._extract_user_id(token)
        if self.user_id:
            logger.info(f"👤 Authenticated as user: {self.user_id}")

        self.timeout = timeout

    @staticmethod
    def _extract_user_id(token: str) -> str | None:
        """
        Extract user identifier from token

        Token format: idt:TKN-XXXX-XXXX:actual_token
        Returns: TKN-XXXX-XXXX (the user identifier)

        Args:
            token: The authentication token (with or without Bearer prefix)

        Returns:
            User identifier (TKN-XXXX-XXXX) or None if not found
        """
        # Remove "Bearer " prefix if present for parsing
        token_value = token.replace(BEARER_PREFIX, "").strip()

        # Check if token matches format: idt:TKN-XXXX-XXXX:token
        if token_value.startswith("idt:") and token_value.count(":") >= 2:
            parts = token_value.split(":")
            if len(parts) >= 3 and parts[1].startswith("TKN-"):
                return parts[1]  # Return TKN-XXXX-XXXX

        return None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication"""
        return {
            "Authorization": self.token,  # Already has Bearer prefix from __init__
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """
        Make a GET request to the API

        Args:
            endpoint: API endpoint path (e.g., "/products" or "/products/{id}")
            params: Query parameters dictionary. Special handling for 'rql' key:
                   - If 'rql' key exists, its value becomes the raw query string directly after '?'
                   - Example: {"rql": "eq(status,Failed)"} → /endpoint?eq(status,Failed)
                   - NOT sent as ?rql=... (it's not a query parameter, it IS the query string)
                   - Other params in the dict are added as normal query parameters
            timeout: Request timeout in seconds

        Returns:
            JSON response from the API

        Raises:
            httpx.HTTPError: If the request fails
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        # Special handling for RQL - it IS the query string, not a query parameter
        # Example: {"rql": "eq(status,Failed)"} becomes "/endpoint?eq(status,Failed)"
        # NOT "/endpoint?rql=eq(status,Failed)"
        original_params = params.copy() if params else {}

        # Build the full URL with all parameters
        if params and "rql" in params:
            rql_query = params.pop("rql")
            # Start with RQL as the base query string
            query_parts = [rql_query]

            # Add remaining params as key=value pairs
            if params:
                additional_query = urlencode(params, doseq=True)
                query_parts.append(additional_query)

            # Construct full URL with all parameters
            url = f"{url}?{'&'.join(query_parts)}"
            # Don't pass params to httpx - we've built the full URL
            params = None

        # Log the API request with user identification
        logger.info("=" * 80)
        logger.info("🔍 Marketplace API Request")
        if self.user_id:
            logger.info(f"   👤 User: {self.user_id}")
        logger.info(f"   Base URL: {self.base_url}")
        logger.info(f"   Endpoint: {endpoint}")
        if original_params:
            logger.info(f"   Parameters: {original_params}")
        logger.info(f"   Full URL: {url}")

        async with httpx.AsyncClient(follow_redirects=True, http2=True, timeout=timeout) as client:
            response = await client.get(
                url,
                params=params,  # Will be None if RQL was used
                headers=headers,
            )
            response.raise_for_status()
            response_data = response.json()

            # Log the API response
            logger.info(f"✅ Response: {response.status_code}")

            # Try to log useful info about the response
            if isinstance(response_data, dict):
                if "data" in response_data:
                    data = response_data["data"]
                    if isinstance(data, list):
                        logger.info(f"   Items returned: {len(data)}")
                    elif isinstance(data, dict):
                        logger.info("   Single item returned")

                # Check for $meta.pagination (SoftwareOne API format)
                if "$meta" in response_data and isinstance(response_data["$meta"], dict):
                    meta = response_data["$meta"]
                    if "pagination" in meta:
                        pagination = meta["pagination"]
                        total = pagination.get("total")
                        offset = pagination.get("offset")
                        limit = pagination.get("limit")
                        logger.info(f"   Pagination: offset={offset}, limit={limit}, total={total}")

                    # Log omitted fields if present
                    if "omitted" in meta:
                        omitted = meta.get("omitted", [])
                        if omitted:
                            logger.info(f"   Omitted fields: {', '.join(omitted)} (use select=+field to include)")
                # Fallback to root-level pagination
                elif "pagination" in response_data:
                    pagination = response_data["pagination"]
                    logger.info(f"   Pagination: {pagination}")
            elif isinstance(response_data, list):
                logger.info(f"   Items returned: {len(response_data)}")

            logger.info("=" * 80)

            return response_data

    async def get_raw(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> str:
        """
        Make a GET request and return raw response text

        Args:
            endpoint: API endpoint path
            params: Query parameters dictionary
            timeout: Request timeout in seconds

        Returns:
            Raw response text from the API
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        async with httpx.AsyncClient(follow_redirects=True, http2=True, timeout=timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            return response.text

    async def validate_token(self) -> bool:
        """
        Validate that the authentication token is valid

        Returns:
            True if token is valid, False otherwise
        """
        try:
            # Try to get user info or health endpoint
            await self.get("/health")
            return True
        except Exception:
            return False
