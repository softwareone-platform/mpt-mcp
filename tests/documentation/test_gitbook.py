from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.documentation.gitbook import GitBookClient, RetryPolicy


@pytest.fixture
def client():
    return GitBookClient(
        api_key="test_api_key", space_id="test_space_id", base_url="https://api.gitbook.com/v1"
    )


@pytest.fixture
def http_get():
    with patch("httpx.AsyncClient") as mock_client:
        get = AsyncMock(return_value=Mock(spec=httpx.Response, status_code=HTTPStatus.OK))
        mock_client.return_value.__aenter__.return_value.get = get
        yield get


@pytest.fixture
def response_factory():
    def factory(status_code=HTTPStatus.OK, headers=None):
        response = Mock(spec=httpx.Response, status_code=status_code, headers=headers or {})
        response.json.return_value = {"id": "page1"}
        return response

    return factory


@pytest.fixture
def sleep():
    with patch("mpt_mcp.documentation.gitbook.asyncio.sleep") as mock_sleep:
        yield mock_sleep


def test_client_initialization():
    result = GitBookClient(
        api_key="test_api_key", space_id="test_space_id", base_url="https://api.gitbook.com/v1"
    )

    assert (result.api_key, result.space_id, result.base_url) == (
        "test_api_key",
        "test_space_id",
        "https://api.gitbook.com/v1",
    )


async def test_fetch_space_content_sends_auth_headers(client, http_get):
    http_get.return_value.json.return_value = {"pages": []}

    await client.fetch_space_content()  # act

    headers = http_get.call_args.kwargs["headers"]
    assert (headers["Authorization"], headers["Accept"]) == (
        "Bearer test_api_key",
        "application/json",
    )


async def test_fetch_space_content(client, http_get):
    space_content = {
        "pages": [
            {"id": "page1", "title": "Getting Started", "path": "getting-started"},
            {"id": "page2", "title": "API Reference", "path": "api-reference"},
        ]
    }
    http_get.return_value.json.return_value = space_content

    result = await client.fetch_space_content()

    assert result == space_content


async def test_fetch_page_by_path(client, http_get):
    page = {
        "id": "page1",
        "title": "Getting Started",
        "path": "getting-started",
        "markdown": "# Getting Started\n\nWelcome to the docs!",
    }
    http_get.return_value.json.return_value = page

    result = await client.fetch_page_by_path("getting-started")

    assert result == page


async def test_validate_credentials_success(client, http_get):
    http_get.return_value.json.return_value = {"id": "test_space_id"}

    result = await client.validate_credentials()

    assert result is True


async def test_validate_credentials_failure(client, http_get):
    http_get.side_effect = httpx.ConnectError("Connection refused")

    result = await client.validate_credentials()

    assert result is False


async def test_validate_credentials_unexpected_error(client, http_get):
    http_get.side_effect = RuntimeError("Unexpected")

    with pytest.raises(RuntimeError, match="Unexpected"):
        await client.validate_credentials()


@pytest.mark.parametrize(
    ("retry_policy", "attempt", "retry_after", "expected"),
    [
        (RetryPolicy(), 1, None, 1.0),
        (RetryPolicy(), 2, None, 2.0),
        (RetryPolicy(), 3, None, 4.0),
        (RetryPolicy(), 1, "5", 5.0),
        (RetryPolicy(), 2, "soon", 2.0),
        (RetryPolicy(backoff_base=0.5, backoff_factor=10), 3, None, 50.0),
    ],
)
def test_retry_policy_delay(retry_policy, attempt, retry_after, expected):
    result = retry_policy.delay(attempt, retry_after)

    assert result == expected


async def test_fetch_page_retries_timeout(client, http_get, response_factory, sleep):
    http_get.side_effect = [TimeoutError(), response_factory()]

    result = await client.fetch_page_by_id("page1")

    assert (result, http_get.call_count) == ({"id": "page1"}, 2)
    sleep.assert_awaited_once_with(1.0)


async def test_fetch_page_retries_rate_limit(client, http_get, response_factory, sleep):
    http_get.side_effect = [
        response_factory(HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "5"}),
        response_factory(HTTPStatus.SERVICE_UNAVAILABLE),
        response_factory(),
    ]

    result = await client.fetch_page_by_id("page1")

    assert (result, http_get.call_count) == ({"id": "page1"}, 3)
    assert [call.args for call in sleep.await_args_list] == [(5.0,), (2.0,)]


async def test_fetch_page_last_timeout(client, http_get, sleep):
    http_get.side_effect = TimeoutError()

    with pytest.raises(TimeoutError):
        await client.fetch_page_by_id("page1")

    assert (http_get.call_count, sleep.await_count) == (3, 2)


async def test_fetch_page_last_rate_limit(client, http_get, response_factory, sleep):
    response = response_factory(HTTPStatus.SERVICE_UNAVAILABLE)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Service Unavailable", request=Mock(spec=httpx.Request), response=response
    )
    http_get.return_value = response

    with pytest.raises(httpx.HTTPStatusError):
        await client.fetch_page_by_id("page1")

    assert (http_get.call_count, sleep.await_count) == (3, 2)


async def test_fetch_page_no_retry_on_error(client, http_get, response_factory, sleep):
    response = response_factory(HTTPStatus.NOT_FOUND)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=Mock(spec=httpx.Request), response=response
    )
    http_get.return_value = response

    with pytest.raises(httpx.HTTPStatusError):
        await client.fetch_page_by_id("page1")

    assert http_get.call_count == 1
    sleep.assert_not_awaited()


async def test_fetch_page_custom_max_attempts(http_get, sleep):
    client = GitBookClient(
        api_key="test_api_key",
        space_id="test_space_id",
        retry_policy=RetryPolicy(max_attempts=2),
    )
    http_get.side_effect = TimeoutError()

    with pytest.raises(TimeoutError):
        await client.fetch_page_by_id("page1")

    assert (http_get.call_count, sleep.await_count) == (2, 1)
