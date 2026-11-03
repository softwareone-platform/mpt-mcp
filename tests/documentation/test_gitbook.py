from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mpt_mcp.documentation.gitbook import GitBookClient


@pytest.fixture
def client():
    return GitBookClient(
        api_key="test_api_key", space_id="test_space_id", base_url="https://api.gitbook.com/v1"
    )


def test_client_initialization():
    result = GitBookClient(
        api_key="test_api_key", space_id="test_space_id", base_url="https://api.gitbook.com/v1"
    )

    assert (result.api_key, result.space_id, result.base_url) == (
        "test_api_key",
        "test_space_id",
        "https://api.gitbook.com/v1",
    )


async def test_fetch_space_content_sends_auth_headers(client):
    response = Mock(status_code=HTTPStatus.OK)
    response.json.return_value = {"pages": []}
    with patch("httpx.AsyncClient") as mock_client:
        get = AsyncMock(return_value=response)
        mock_client.return_value.__aenter__.return_value.get = get

        await client.fetch_space_content()  # act

    headers = get.call_args.kwargs["headers"]
    assert (headers["Authorization"], headers["Accept"]) == (
        "Bearer test_api_key",
        "application/json",
    )


async def test_fetch_space_content(client):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "pages": [
            {"id": "page1", "title": "Getting Started", "path": "getting-started"},
            {"id": "page2", "title": "API Reference", "path": "api-reference"},
        ]
    }
    mock_response.raise_for_status = Mock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_context

        space_content = await client.fetch_space_content()

        assert "pages" in space_content
        assert len(space_content["pages"]) == 2


async def test_fetch_page_by_path(client):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "page1",
        "title": "Getting Started",
        "path": "getting-started",
        "markdown": "# Getting Started\n\nWelcome to the docs!",
    }
    mock_response.raise_for_status = Mock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_context

        page = await client.fetch_page_by_path("getting-started")

        assert page["id"] == "page1"
        assert page["title"] == "Getting Started"
        assert "markdown" in page


async def test_validate_credentials_success(client):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status = Mock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_context

        is_valid = await client.validate_credentials()

        assert is_valid is True


async def test_validate_credentials_failure(client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(side_effect=Exception("Unauthorized"))
        mock_client.return_value = mock_context

        is_valid = await client.validate_credentials()

        assert is_valid is False
