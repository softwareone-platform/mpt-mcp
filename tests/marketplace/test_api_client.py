import asyncio
import logging
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.marketplace.api_client import APIClient, normalize_endpoint_url

API_BASE_URL = "https://api.example.com"
PAGE_SIZE = 5
PRODUCTS_ENDPOINT = "/public/v1/catalog/products"
PRODUCTS_URL = f"https://api.test.com{PRODUCTS_ENDPOINT}"
ORDERS_ENDPOINT = "/public/v1/commerce/orders"
REAL_IDT_TOKEN = (
    "idt:TKN-0291-1452:4l6Fq7jrGSfZVjDYHabJkxTuv4nynuj5f8qVTbbHJS5rFXpetnvRYfvwiaRjGzrF"
)
TIMEOUT = 30.0


@pytest.fixture
def http_get():
    response = Mock(spec=httpx.Response, status_code=HTTPStatus.OK)
    response.json.return_value = {"data": []}
    with patch("httpx.AsyncClient") as mock_client:
        get = AsyncMock(return_value=response)
        mock_client.return_value.__aenter__.return_value.get = get
        yield get


@pytest.fixture
def api_client():
    return APIClient(base_url="https://api.test.com", token="test_token", timeout=TIMEOUT)


@pytest.fixture
def products_response():
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


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.s1.show/public", "https://api.s1.show"),
        ("https://api.platform.softwareone.com/", "https://api.platform.softwareone.com"),
        ("https://api.s1.show/v1/api/anything", "https://api.s1.show"),
        ("https://api.platform.softwareone.com", "https://api.platform.softwareone.com"),
        ("http://localhost:8080/some/path", "http://localhost:8080"),
        ("http://api.example.com/path", "http://api.example.com"),
        (
            "https://api.staging.platform.softwareone.com/public/v1",
            "https://api.staging.platform.softwareone.com",
        ),
    ],
)
def test_api_client_normalizes_base_url(base_url, expected):
    result = APIClient(base_url=base_url, token="test-token")

    assert result.base_url == expected


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://api.s1.show/public", "https://api.s1.show"),
        ("https://api.s1.show/public/", "https://api.s1.show"),
        ("https://api.s1.show/public/v1", "https://api.s1.show"),
        ("https://api.s1.show", "https://api.s1.show"),
        ("https://api.s1.show//", "https://api.s1.show"),
        ("http://localhost:8080/public", "http://localhost:8080"),
        ("https://api.example.com/api/v1", "https://api.example.com"),
        ("api.s1.show", "api.s1.show"),
        ("/public", "/public"),
        ("", ""),
    ],
)
def test_normalize_endpoint_url(endpoint, expected):
    result = normalize_endpoint_url(endpoint)

    assert result == expected


@pytest.mark.parametrize(
    "base_url",
    ["https://api.s1.show/public", "https://api.s1.show/v1", "https://api.s1.show"],
)
def test_api_client_prevents_path_duplication(base_url):
    client = APIClient(base_url=base_url, token="test-token")

    result = f"{client.base_url}{PRODUCTS_ENDPOINT}"

    assert result == "https://api.s1.show/public/v1/catalog/products"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("my-token-value", "Bearer my-token-value"),
        ("Bearer my-token-value", "Bearer my-token-value"),
        ("bearer my-token", "Bearer bearer my-token"),
        ("idt:TKN-1234-5678:abc123XYZ_-.", "Bearer idt:TKN-1234-5678:abc123XYZ_-."),
        ("idt:TKN-1234-5678:secret", "Bearer idt:TKN-1234-5678:secret"),
        ("Bearer idt:TKN-1234-5678:secret", "Bearer idt:TKN-1234-5678:secret"),
    ],
)
def test_token_gets_bearer_prefix(token, expected):
    result = APIClient(base_url=API_BASE_URL, token=token)

    assert result.token == expected


@pytest.mark.parametrize(
    ("token", "expected_user_id"),
    [
        (REAL_IDT_TOKEN, "TKN-0291-1452"),
        ("Bearer idt:TKN-1234-5678:abc123", "TKN-1234-5678"),
        ("idt:TKN-0000-0000:token", "TKN-0000-0000"),
        ("idt:TKN-9999-9999:token", "TKN-9999-9999"),
        ("idt:TKN-1111-2222:token", "TKN-1111-2222"),
        ("simple-token", None),
        ("Bearer simple-token", None),
        ("jwt.token.here", None),
        ("api-key-12345", None),
        ("idt:TOKEN-123:value", None),  # TOKEN instead of TKN
        ("idt:TKN-123", None),  # missing third part
        ("idt:", None),
        ("TKN-1234-5678:token", None),  # missing idt: prefix
        ("TKN-1234-5678", None),
    ],
)
def test_user_id_from_token(token, expected_user_id):
    client = APIClient(base_url=API_BASE_URL, token=token)

    result = client.user_id

    assert result == expected_user_id


def test_real_world_token_example():
    result = APIClient(base_url="https://api.s1.show/public", token=REAL_IDT_TOKEN)

    assert (result.base_url, result.token, result.user_id) == (
        "https://api.s1.show",
        f"Bearer {REAL_IDT_TOKEN}",
        "TKN-0291-1452",
    )


@pytest.mark.parametrize(
    ("token", "expected_authorization"),
    [
        ("my-token", "Bearer my-token"),
        ("idt:TKN-0291-1452:secret", "Bearer idt:TKN-0291-1452:secret"),
        ("Bearer idt:TKN-0291-1452:secret", "Bearer idt:TKN-0291-1452:secret"),
    ],
)
async def test_get_sends_normalized_bearer_token(http_get, token, expected_authorization):
    client = APIClient(base_url=API_BASE_URL, token=token)

    await client.get(PRODUCTS_ENDPOINT)  # act

    assert http_get.call_args.kwargs["headers"]["Authorization"] == expected_authorization


async def test_get_returns_response_json(api_client, http_get, products_response):
    http_get.return_value.json.return_value = products_response

    result = await api_client.get(PRODUCTS_ENDPOINT, query_params={"limit": 1})

    assert result == products_response


@pytest.mark.parametrize(
    ("query_params", "expected_url"),
    [
        (
            {"rql": "eq(status,Published)", "limit": 1},
            f"{PRODUCTS_URL}?eq(status,Published)&limit=1",
        ),
        (
            {"rql": "ilike(name,*Microsoft*)", "limit": 5},
            f"{PRODUCTS_URL}?ilike(name,*Microsoft*)&limit=5",
        ),
        (
            {"rql": "order=-id&limit=3"},
            f"{PRODUCTS_URL}?order=-id&limit=3",
        ),
        (
            {"rql": "and(eq(status,Published),ilike(name,*AWS*))", "limit": 5},
            f"{PRODUCTS_URL}?and(eq(status,Published),ilike(name,*AWS*))&limit=5",
        ),
    ],
)
async def test_get_sends_rql_as_query_string(api_client, http_get, query_params, expected_url):
    await api_client.get(PRODUCTS_ENDPOINT, query_params=query_params)  # act

    assert http_get.call_args.args == (expected_url,)
    assert http_get.call_args.kwargs["params"] is None


async def test_get_sends_query_params_without_rql(api_client, http_get):
    query_params = {"select": "+id,+name", "limit": 1}

    await api_client.get(PRODUCTS_ENDPOINT, query_params=query_params)  # act

    assert http_get.call_args.kwargs["params"] == query_params


async def test_get_paginates_with_offset(api_client, http_get):
    pages = [
        {"data": [{"id": f"prod-{index}"} for index in range(first, first + PAGE_SIZE)]}
        for first in (1, PAGE_SIZE + 1)
    ]
    http_get.return_value.json.side_effect = pages

    result = await asyncio.gather(
        *(
            api_client.get(PRODUCTS_ENDPOINT, query_params={"limit": PAGE_SIZE, "offset": offset})
            for offset in (0, PAGE_SIZE)
        )
    )

    assert result == pages


@pytest.mark.parametrize(
    "status",
    [
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
    ],
)
async def test_get_raises_http_errors(api_client, http_get, status):
    error_response = Mock(spec=httpx.Response, status_code=status, text=status.phrase)
    http_get.side_effect = httpx.HTTPStatusError(
        f"{status.value} {status.phrase}", request=Mock(spec=httpx.Request), response=error_response
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await api_client.get("/products")

    assert exc_info.value.response.status_code == status


async def test_get_logs_request_url(api_client, http_get, caplog):
    with caplog.at_level(logging.INFO, logger="mpt_mcp.marketplace.api_client"):
        await api_client.get(ORDERS_ENDPOINT, query_params={"limit": 10})  # act

    assert f"Marketplace API request: https://api.test.com{ORDERS_ENDPOINT}?limit=10" in caplog.text


@pytest.mark.parametrize(
    ("response_data", "expected"),
    [
        (
            {
                "data": [{"id": "ORD-123"}],
                "$meta": {
                    "pagination": {"total": 45, "limit": 10, "offset": 0},
                    "omitted": ["lines", "assets"],
                },
            },
            "items=1, offset=0, limit=10, total=45, omitted fields: lines, assets",
        ),
        ({"id": "ORD-123", "status": "Completed"}, "single item"),
        ([{"id": "ORD-123"}, {"id": "ORD-456"}], "items=2"),
    ],
)
async def test_get_logs_response_summary(api_client, http_get, caplog, response_data, expected):
    http_get.return_value.status_code = HTTPStatus.OK
    http_get.return_value.json.return_value = response_data

    with caplog.at_level(logging.INFO, logger="mpt_mcp.marketplace.api_client"):
        await api_client.get(ORDERS_ENDPOINT)  # act

    assert f"Marketplace API response 200: {expected}" in caplog.text


@pytest.mark.parametrize(
    "meta",
    [
        {"pagination": {"total": 1, "limit": 10, "offset": 0}},
        {"pagination": {"total": 1, "limit": 10, "offset": 0}, "omitted": []},
    ],
)
async def test_handles_response_without_omitted_fields(api_client, http_get, meta):
    http_get.return_value.json.return_value = {"data": [], "$meta": meta}

    result = await api_client.get(ORDERS_ENDPOINT, query_params={"limit": 10})

    assert result["$meta"] == meta
