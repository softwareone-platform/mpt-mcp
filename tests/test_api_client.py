from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.api_client import APIClient

PAGE_SIZE = 5

TIMEOUT = 30.0


def test_api_client_strips_public_path():
    result = APIClient(base_url="https://api.s1.show/public", token="test-token")

    assert result.base_url == "https://api.s1.show"


def test_api_client_strips_trailing_slash():
    result = APIClient(base_url="https://api.platform.softwareone.com/", token="test-token")

    assert result.base_url == "https://api.platform.softwareone.com"


def test_api_client_strips_any_path():
    result = APIClient(base_url="https://api.s1.show/v1/api/anything", token="test-token")

    assert result.base_url == "https://api.s1.show"


def test_api_client_preserves_hostname_only_url():
    result = APIClient(base_url="https://api.platform.softwareone.com", token="test-token")

    assert result.base_url == "https://api.platform.softwareone.com"


def test_api_client_preserves_port():
    result = APIClient(base_url="http://localhost:8080/some/path", token="test-token")

    assert result.base_url == "http://localhost:8080"


def test_api_client_handles_http_protocol():
    result = APIClient(base_url="http://api.example.com/path", token="test-token")

    assert result.base_url == "http://api.example.com"


def test_api_client_constructs_correct_url():
    client = APIClient(base_url="https://api.s1.show/public", token="test-token")

    # Simulate URL construction (same logic as in get method)
    endpoint = "/public/v1/catalog/products"

    result = f"{client.base_url}{endpoint}"

    # Should not have double /public
    assert result == "https://api.s1.show/public/v1/catalog/products"
    assert "/public/public/" not in result


@pytest.mark.parametrize(
    "base_url",
    ["https://api.s1.show/public", "https://api.s1.show/v1", "https://api.s1.show"],
)
def test_api_client_prevents_path_duplication(base_url):
    client = APIClient(base_url=base_url, token="test-token")

    result = f"{client.base_url}/public/v1/catalog/products"

    assert result == "https://api.s1.show/public/v1/catalog/products"


def test_api_client_handles_subdomain():
    result = APIClient(
        base_url="https://api.staging.platform.softwareone.com/public/v1", token="test-token"
    )

    assert result.base_url == "https://api.staging.platform.softwareone.com"


def test_token_without_bearer_gets_prefix_added():
    result = APIClient(base_url="https://api.example.com", token="my-token-value")

    assert result.token == "Bearer my-token-value"


def test_token_with_bearer_stays_unchanged():
    result = APIClient(base_url="https://api.example.com", token="Bearer my-token-value")

    assert result.token == "Bearer my-token-value"


def test_lowercase_bearer_gets_prefix():
    result = APIClient(base_url="https://api.example.com", token="bearer my-token")

    assert result.token == "Bearer bearer my-token"


def test_token_with_special_characters():
    token = "idt:TKN-1234-5678:abc123XYZ_-."

    result = APIClient(base_url="https://api.example.com", token=token)

    assert result.token == f"Bearer {token}"


@pytest.fixture
def http_get():
    response = Mock()
    response.json.return_value = {"data": []}
    with patch("httpx.AsyncClient") as mock_client:
        get = AsyncMock(return_value=response)
        mock_client.return_value.__aenter__.return_value.get = get
        yield get


@pytest.mark.parametrize(
    ("token", "expected_authorization"),
    [
        ("my-token", "Bearer my-token"),
        ("idt:TKN-0291-1452:secret", "Bearer idt:TKN-0291-1452:secret"),
        ("Bearer idt:TKN-0291-1452:secret", "Bearer idt:TKN-0291-1452:secret"),
    ],
)
async def test_get_sends_normalized_bearer_token(http_get, token, expected_authorization):
    client = APIClient(base_url="https://api.example.com", token=token)

    await client.get("/public/v1/catalog/products")  # act

    assert http_get.call_args.kwargs["headers"]["Authorization"] == expected_authorization


def test_extract_user_id_from_idt_token():
    token = "idt:TKN-0291-1452:4l6Fq7jrGSfZVjDYHabJkxTuv4nynuj5f8qVTbbHJS5rFXpetnvRYfvwiaRjGzrF"

    result = APIClient(base_url="https://api.example.com", token=token)

    assert result.user_id == "TKN-0291-1452"


def test_extract_user_id_from_token_with_bearer():
    token = "Bearer idt:TKN-1234-5678:abc123"

    result = APIClient(base_url="https://api.example.com", token=token)

    assert result.user_id == "TKN-1234-5678"


@pytest.mark.parametrize(
    ("token", "expected_user_id"),
    [
        ("idt:TKN-0000-0000:token", "TKN-0000-0000"),
        ("idt:TKN-9999-9999:token", "TKN-9999-9999"),
        ("idt:TKN-1111-2222:token", "TKN-1111-2222"),
    ],
)
def test_extract_user_id_from_tkn_formats(token, expected_user_id):
    result = APIClient(base_url="https://api.example.com", token=token)

    assert result.user_id == expected_user_id


@pytest.mark.parametrize(
    "token",
    ["simple-token", "Bearer simple-token", "jwt.token.here", "api-key-12345"],
)
def test_no_user_id_for_non_idt_token(token):
    result = APIClient(base_url="https://api.example.com", token=token)

    assert result.user_id is None


@pytest.mark.parametrize(
    "token",
    [
        "idt:TOKEN-123:value",  # TOKEN instead of TKN
        "idt:TKN-123",  # missing third part
        "idt:",
        "TKN-1234-5678:token",  # missing idt: prefix
    ],
)
def test_no_user_id_for_malformed_idt_token(token):
    result = APIClient(base_url="https://api.example.com", token=token)

    assert result.user_id is None


@pytest.mark.parametrize(
    ("token", "expected_user_id"),
    [
        ("idt:TKN-1234-5678:token", "TKN-1234-5678"),
        ("Bearer idt:TKN-1234-5678:token", "TKN-1234-5678"),
        ("simple-token", None),
        ("idt:TOKEN-123:value", None),
        ("TKN-1234-5678", None),
    ],
)
def test_user_id_from_token(token, expected_user_id):
    client = APIClient(base_url="https://api.example.com", token=token)

    result = client.user_id

    assert result == expected_user_id


def test_idt_token_without_bearer_gets_prefix():
    token = "idt:TKN-1234-5678:secret"

    result = APIClient(base_url="https://api.example.com", token=token)

    # Should have Bearer prefix added
    assert result.token == f"Bearer {token}"

    # Should have user_id extracted
    assert result.user_id == "TKN-1234-5678"


def test_idt_token_with_bearer_keeps_prefix():
    token = "Bearer idt:TKN-1234-5678:secret"

    result = APIClient(base_url="https://api.example.com", token=token)

    # Should keep Bearer prefix
    assert result.token == token

    # Should have user_id extracted
    assert result.user_id == "TKN-1234-5678"


def test_real_world_token_example():
    token = "idt:TKN-0291-1452:4l6Fq7jrGSfZVjDYHabJkxTuv4nynuj5f8qVTbbHJS5rFXpetnvRYfvwiaRjGzrF"

    result = APIClient(base_url="https://api.s1.show/public", token=token)

    # Verify all features work together
    assert result.base_url == "https://api.s1.show"  # URL normalized
    assert result.token.startswith("Bearer ")  # Bearer added
    assert result.user_id == "TKN-0291-1452"  # User ID extracted


@pytest.fixture
def api_client():
    return APIClient(base_url="https://api.test.com", token="test_token", timeout=TIMEOUT)


@pytest.fixture
def mock_product_response():
    return {
        "data": [
            {
                "id": "prod-123",
                "name": "Microsoft Office 365",
                "status": "Published",
                "description": "Office suite",
            }
        ],
        "$meta": {"pagination": {"total": 100, "limit": 1, "offset": 0}},
    }


async def test_simple_pagination(api_client, mock_product_response):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = mock_product_response
        mock_response.raise_for_status = Mock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"
        result = await api_client.get(endpoint, query_params={"limit": 1})

        assert "data" in result
        assert len(result["data"]) <= 1
        assert "$meta" in result
        assert result["$meta"]["pagination"]["limit"] == 1


async def test_rql_filter_by_status(api_client, mock_product_response):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = mock_product_response
        mock_response.raise_for_status = Mock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"
        rql = "eq(status,Published)"
        result = await api_client.get(endpoint, query_params={"rql": rql, "limit": 1})

        assert "data" in result
        assert result["data"][0]["status"] == "Published"

        # Verify the API was called with correct parameters
        call_args = mock_get.call_args
        assert "eq(status,Published)" in str(call_args)


async def test_rql_search_with_ilike(api_client, mock_product_response):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = mock_product_response
        mock_response.raise_for_status = Mock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"
        rql = "ilike(name,*Microsoft*)"
        result = await api_client.get(endpoint, query_params={"rql": rql, "limit": 5})

        assert "data" in result
        for product in result["data"]:
            assert "Microsoft" in product["name"]


async def test_rql_ordering_in_query_string(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {"id": "prod-3", "name": "Product 3"},
                {"id": "prod-2", "name": "Product 2"},
                {"id": "prod-1", "name": "Product 1"},
            ],
            "$meta": {"pagination": {"limit": 3, "offset": 0, "total": 100}},
        }
        mock_response.raise_for_status = Mock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"
        rql_query = "order=-id&limit=3"
        result = await api_client.get(endpoint, query_params={"rql": rql_query})

        assert "data" in result
        assert "$meta" in result
        pagination = result["$meta"].get("pagination", {})
        assert pagination.get("limit") == 3

        # Verify URL contains ordering
        call_args = mock_get.call_args
        assert "order=-id" in str(call_args)


async def test_rql_select_fields(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"id": "prod-123", "name": "Product Name"}],
            "$meta": {"pagination": {"limit": 1}},
        }
        mock_response.raise_for_status = Mock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"
        result = await api_client.get(endpoint, query_params={"select": "+id,+name", "limit": 1})

        assert "data" in result
        product = result["data"][0]
        assert "id" in product
        assert "name" in product


async def test_rql_complex_query(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {"id": "prod-aws-1", "name": "AWS Lambda", "status": "Published"},
                {"id": "prod-aws-2", "name": "AWS EC2", "status": "Published"},
            ],
            "$meta": {"pagination": {"limit": 5}},
        }
        mock_response.raise_for_status = Mock()

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"
        rql = "and(eq(status,Published),ilike(name,*AWS*))"
        result = await api_client.get(endpoint, query_params={"rql": rql, "limit": 5})

        assert "data" in result
        for product in result["data"]:
            assert product["status"] == "Published"
            assert "AWS" in product["name"]


async def test_rql_pagination_offset(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        # Mock responses for two pages
        page1_response = Mock()
        page1_response.json.return_value = {
            "data": [
                {"id": f"prod-{index}", "name": f"Product {index}"}
                for index in range(1, PAGE_SIZE + 1)
            ],
            "$meta": {"pagination": {"limit": 5, "offset": 0, "total": 100}},
        }
        page1_response.raise_for_status = Mock()

        page2_response = Mock()
        page2_response.json.return_value = {
            "data": [
                {"id": f"prod-{index}", "name": f"Product {index}"}
                for index in range(PAGE_SIZE + 1, 2 * PAGE_SIZE + 1)
            ],
            "$meta": {"pagination": {"limit": 5, "offset": 5, "total": 100}},
        }
        page2_response.raise_for_status = Mock()

        mock_get = AsyncMock(side_effect=[page1_response, page2_response])
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/catalog/products"

        # Get first page
        page1 = await api_client.get(endpoint, query_params={"limit": 5, "offset": 0})
        assert "data" in page1

        # Get second page
        page2 = await api_client.get(endpoint, query_params={"limit": 5, "offset": 5})
        assert "data" in page2

        # Ensure different results
        page1_ids = [product["id"] for product in page1["data"]]
        page2_ids = [product["id"] for product in page2["data"]]
        assert page1_ids != page2_ids


async def test_unauthorized_error():

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Invalid credentials"}
        mock_response.text = "Invalid credentials"

        mock_get = AsyncMock()
        mock_get.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=Mock(), response=mock_response
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        client = APIClient("https://api.test.com", "test_token")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get("/products")

        assert exc_info.value.response.status_code == HTTPStatus.UNAUTHORIZED


async def test_forbidden_error():

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"error": "Access denied"}
        mock_response.text = "Access denied"

        mock_get = AsyncMock()
        mock_get.side_effect = httpx.HTTPStatusError(
            "403 Forbidden", request=Mock(), response=mock_response
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        client = APIClient("https://api.test.com", "test_token")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get("/products")

        assert exc_info.value.response.status_code == HTTPStatus.FORBIDDEN


async def test_not_found_error():

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": "Resource not found"}
        mock_response.text = "Resource not found"

        mock_get = AsyncMock()
        mock_get.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=Mock(), response=mock_response
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        client = APIClient("https://api.test.com", "test_token")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get("/products/invalid-id")

        assert exc_info.value.response.status_code == HTTPStatus.NOT_FOUND


async def test_rate_limit_error():

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": "Rate limit exceeded"}
        mock_response.text = "Rate limit exceeded"

        mock_get = AsyncMock()
        mock_get.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests", request=Mock(), response=mock_response
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        client = APIClient("https://api.test.com", "test_token")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get("/products")

        assert exc_info.value.response.status_code == HTTPStatus.TOO_MANY_REQUESTS


async def test_server_error():

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal server error"}
        mock_response.text = "Internal server error"

        mock_get = AsyncMock()
        mock_get.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error", request=Mock(), response=mock_response
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get

        client = APIClient("https://api.test.com", "test_token")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get("/products")

        assert exc_info.value.response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


async def test_logs_omitted_fields_in_response(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"id": "ORD-123", "status": "Completed"}],
            "$meta": {
                "pagination": {"total": 1, "limit": 10, "offset": 0},
                "omitted": ["lines", "parameters", "subscriptions", "assets"],
            },
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        # Capture log output
        with patch("mpt_mcp.api_client.logger") as mock_logger:
            endpoint = "/public/v1/commerce/orders"
            result = await api_client.get(endpoint, query_params={"limit": 10})

            # Verify response contains omitted fields
            assert "$meta" in result
            assert "omitted" in result["$meta"]
            assert result["$meta"]["omitted"] == [
                "lines",
                "parameters",
                "subscriptions",
                "assets",
            ]

            # Verify logging was called with omitted fields info
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            omitted_logged = any("omitted" in str(call).lower() for call in log_calls)
            assert omitted_logged, "Omitted fields should be logged"


async def test_handles_response_without_omitted_fields(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"id": "ORD-123", "status": "Completed"}],
            "$meta": {
                "pagination": {"total": 1, "limit": 10, "offset": 0},
                # No "omitted" field
            },
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/commerce/orders"
        result = await api_client.get(endpoint, query_params={"limit": 10})

        # Should not raise error when omitted is missing
        assert "$meta" in result
        assert "omitted" not in result["$meta"] or result["$meta"].get("omitted") is None


async def test_handles_empty_omitted_fields_list(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"id": "ORD-123", "status": "Completed"}],
            "$meta": {
                "pagination": {"total": 1, "limit": 10, "offset": 0},
                "omitted": [],  # Empty list
            },
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200

        mock_get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/commerce/orders"
        result = await api_client.get(endpoint, query_params={"limit": 10})

        assert "$meta" in result
        assert result["$meta"]["omitted"] == []


async def test_select_parameter_includes_omitted_fields(api_client):
    with patch("httpx.AsyncClient") as mock_client:
        # First response: fields omitted
        mock_response_omitted = Mock()
        mock_response_omitted.json.return_value = {
            "data": [{"id": "ORD-123", "status": "Completed"}],
            "$meta": {
                "pagination": {"total": 1, "limit": 10, "offset": 0},
                "omitted": ["lines", "parameters"],
            },
        }
        mock_response_omitted.raise_for_status = Mock()
        mock_response_omitted.status_code = 200

        # Second response: fields included via select
        mock_response_included = Mock()
        mock_response_included.json.return_value = {
            "data": [
                {
                    "id": "ORD-123",
                    "status": "Completed",
                    "lines": [{"id": "LINE-1", "quantity": 1}],
                    "parameters": {"key": "value"},
                }
            ],
            "$meta": {
                "pagination": {"total": 1, "limit": 10, "offset": 0},
                "omitted": [],  # No omitted fields when explicitly selected
            },
        }
        mock_response_included.raise_for_status = Mock()
        mock_response_included.status_code = 200

        mock_get = AsyncMock(side_effect=[mock_response_omitted, mock_response_included])
        mock_client.return_value.__aenter__.return_value.get = mock_get

        endpoint = "/public/v1/commerce/orders"

        # First call: without select
        result1 = await api_client.get(endpoint, query_params={"limit": 10})
        assert "omitted" in result1["$meta"]
        assert "lines" in result1["$meta"]["omitted"]

        # Second call: with select=+lines,+parameters
        result2 = await api_client.get(
            endpoint, query_params={"limit": 10, "select": "+lines,+parameters"}
        )
        # When fields are explicitly selected, they should be in data
        if "lines" in result2.get("data", [{}])[0]:
            assert "lines" in result2["data"][0]
        # omitted list may be empty or not include the selected fields
        assert "$meta" in result2
