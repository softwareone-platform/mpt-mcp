from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.documentation.gitbook import GitBookClient


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
    http_get.side_effect = RuntimeError("Unauthorized")

    result = await client.validate_credentials()

    assert result is False
