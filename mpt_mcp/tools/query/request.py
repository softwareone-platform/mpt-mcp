import logging
import time
from http import HTTPStatus
from itertools import starmap
from typing import TYPE_CHECKING, Any

import httpx

from mpt_mcp.analytics.events import ApiQueryEvent
from mpt_mcp.tools.results import KEY_META, tool_error

if TYPE_CHECKING:
    from fastmcp.exceptions import ToolError

    from mpt_mcp.analytics import AnalyticsLogger
    from mpt_mcp.marketplace.api_client import APIClient
    from mpt_mcp.tools.query.params import QueryParams

logger = logging.getLogger(__name__)

API_ERROR_TEXT_MAX_LENGTH = 500
# API validation messages for a field path the resource does not have
UNKNOWN_FIELD_MESSAGES = ("Unknown expression group", "Invalid property path")
# What APIClient.get raises: request failures and error statuses, or a body that is not JSON
API_REQUEST_ERRORS = (httpx.HTTPError, ValueError)


class MarketplaceRequest:
    """GET request of marketplace_query to one API path, recorded in the analytics."""

    def __init__(
        self,
        resource: str,
        api_path: str,
        api_client: APIClient,
        analytics_logger: AnalyticsLogger | None,
    ) -> None:
        self.analytics_logger = analytics_logger
        self.api_client = api_client
        self.api_path = api_path
        self.resource = resource
        self.start_time = time.monotonic()

    async def send(self, query: QueryParams, fallback_query: QueryParams | None) -> Any:
        """
        Send the query, and retry it with fallback_query when the API rejects it with a 400.

        Args:
            query: Query to send
            fallback_query: Query without the audit fields added to select, or None

        Returns:
            API response: usually an object, but some resources return a plain value

        Raises:
            ToolError: The API call failed; the error describes the API error
        """
        try:
            result, sent_query = await self._get_with_fallback(query, fallback_query)
        except API_REQUEST_ERRORS as error:
            logger.warning("Error: %s", error)
            status_code = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            await self._record(query, status_code, result_count=None)
            raise self._tool_error(error) from error

        await self._record(sent_query, HTTPStatus.OK, result_count=get_result_total(result))
        return result

    async def _get(self, query: QueryParams) -> Any:
        query_params = query.to_query()
        logger.info("Query: %s", self.resource)
        logger.info("Path: %s", self.api_path)
        logger.info("Params: %s", query_params)
        result = await self.api_client.get(self.api_path, query_params=query_params)
        total = get_result_total(result)
        if total is not None:
            logger.info("Result: %s total items", total)

        # SECURITY: hide the token values of every API token endpoint, matched by path
        if "/accounts/api-tokens" in self.api_path.lower():
            logger.info("Obfuscating token values in response (security)")
            return obfuscate_token_values(result)

        return result

    async def _get_with_fallback(
        self, query: QueryParams, fallback_query: QueryParams | None
    ) -> tuple[Any, QueryParams]:
        if fallback_query is None:
            return await self._get(query), query

        try:
            return await self._get(query), query
        except httpx.HTTPStatusError as error:
            if error.response.status_code != HTTPStatus.BAD_REQUEST:
                raise
            rejected_error = error

        logger.info(
            "400 error after auto-adding audit fields - retrying with select: %s",
            fallback_query.select or "None",
        )
        try:
            return await self._get(fallback_query), fallback_query
        except API_REQUEST_ERRORS as retry_error:
            logger.warning("Retry also failed: %s", retry_error)
            raise rejected_error from retry_error

    async def _record(self, query: QueryParams, status_code: int, result_count: int | None) -> None:
        if self.analytics_logger is None:
            return

        await self.analytics_logger.record(
            ApiQueryEvent(
                api_resource=self.resource,
                api_path=self.api_path,
                api_status_code=status_code,
                api_response_time_ms=int((time.monotonic() - self.start_time) * 1000),
                result_count=result_count,
                rql_filter=query.rql,
                limit_value=query.limit,
                offset_value=query.offset,
                order_by=query.order,
                select_fields=query.select,
            )
        )

    def _tool_error(self, error: Exception) -> ToolError:
        details: dict[str, Any] = {"resource": self.resource, "path": self.api_path}
        if isinstance(error, httpx.HTTPStatusError):
            details |= get_http_error_details(error)
        return tool_error(str(error), **details)


def get_http_error_details(error: httpx.HTTPStatusError) -> dict[str, Any]:
    """
    Describe an API error for the caller.

    Args:
        error: Error status returned by the Marketplace API

    Returns:
        Status code, request URL, the API error body (or its text when it is not JSON), and a
        hint when the query used an audit field the resource does not have
    """
    details: dict[str, Any] = {
        "status_code": error.response.status_code,
        "request_url": str(error.request.url),
    }
    try:
        error_body = error.response.json()
    except ValueError:
        details["api_error_text"] = error.response.text[:API_ERROR_TEXT_MAX_LENGTH]
        return details

    details["api_error_details"] = error_body
    errors = error_body.get("errors") if isinstance(error_body, dict) else None
    if isinstance(errors, dict) and any(starmap(is_unknown_audit_error, errors.items())):
        details["hint"] = (
            "The resource does not have this audit field: list its audit events with "
            "marketplace_audit_fields(resource)"
        )
    return details


def get_result_total(result: Any) -> int | None:
    """Return the number of items that match the query, when the API response gives it."""
    meta = result.get(KEY_META) if isinstance(result, dict) else None
    pagination = meta.get("pagination") if isinstance(meta, dict) else None
    return pagination.get("total") if isinstance(pagination, dict) else None


def is_unknown_audit_error(field: str, messages: Any) -> bool:
    """Tell whether an API validation error says the resource has no such audit field."""
    if not isinstance(messages, list):
        return False

    texts = [str(message) for message in messages]
    if not any(marker in text for text in texts for marker in UNKNOWN_FIELD_MESSAGES):
        return False

    mentions_audit = any("audit" in text.lower() for text in texts)
    return mentions_audit or "audit" in field.lower()


def obfuscate_token_values(data: Any) -> Any:
    """
    Recursively obfuscate 'token' property values in API responses.

    SECURITY: This prevents sensitive token values from being exposed in API responses.
    When querying token-related resources (e.g., accounts.api-tokens), the actual token
    values are replaced with '[REDACTED]' to protect sensitive credentials.

    Args:
        data: The data structure to sanitize (dict, list, or primitive)

    Returns:
        Sanitized data structure with token values obfuscated
    """
    if isinstance(data, dict):
        sanitized = {}
        for key, field_value in data.items():
            if key.lower() == "token" and isinstance(field_value, str) and field_value.strip():
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = obfuscate_token_values(field_value)
        return sanitized

    if isinstance(data, list):
        return [obfuscate_token_values(element) for element in data]

    return data
