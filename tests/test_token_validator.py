import base64
import json
import time
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mpt_mcp.token_validator import (
    TokenValidationCache,
    config,
    normalize_token,
    parse_jwt_claims,
    parse_token_id,
    validate_token,
)

API_BASE_URL = "https://api.test.com"
EXPIRED_SECONDS_AGO = 200  # beyond the default 120 s leeway
ISSUED_SECONDS_AGO = 3600
JWT_USER_ID = "USR-1234-5678"
RSA_KEY_SIZE = 2048
RSA_PUBLIC_EXPONENT = 65537
SLUG_TRANSLATION = str.maketrans({"_": "-", "[": "-", "]": None})
TOKEN_CACHE_TTL_MINUTES = 30
WIDE_LEEWAY_SECONDS = 300


def test_cache_initialization():
    cache = TokenValidationCache(ttl_minutes=TOKEN_CACHE_TTL_MINUTES)

    result = cache.get_stats()

    assert (result["total_entries"], result["ttl_minutes"]) == (0, 30)


async def test_cache_set_and_get():
    cache = TokenValidationCache(ttl_minutes=60)
    token_info = {"account": {"id": "ACC-123", "name": "Test"}}
    await cache.set("idt:TKN-1234-5678-SECRET", API_BASE_URL, is_valid=True, token_info=token_info)

    result = await cache.get("idt:TKN-1234-5678-SECRET", API_BASE_URL)

    assert result == (True, token_info)


@pytest.mark.parametrize(
    ("token", "endpoint"),
    [
        ("idt:TKN-1234-5678-SECRET2", API_BASE_URL),
        ("idt:TKN-1234-5678-SECRET1", "https://api.other.com"),
    ],
)
async def test_cache_keys_differ_per_token_and_endpoint(token, endpoint):
    cache = TokenValidationCache()
    await cache.set("idt:TKN-1234-5678-SECRET1", API_BASE_URL, is_valid=True, token_info={})

    result = await cache.get(token, endpoint)

    assert result is None


async def test_cache_miss():
    cache = TokenValidationCache()

    result = await cache.get("idt:TKN-1234-5678-SECRET", API_BASE_URL)

    assert result is None


async def test_cache_expiry():
    cache = TokenValidationCache(ttl_minutes=0)
    await cache.set(
        "idt:TKN-1234-5678-SECRET",
        API_BASE_URL,
        is_valid=True,
        token_info={"account": {"id": "ACC-123"}},
    )

    result = await cache.get("idt:TKN-1234-5678-SECRET", API_BASE_URL)

    assert result is None


async def test_cache_stores_invalid_tokens():
    cache = TokenValidationCache()
    await cache.set("idt:TKN-INVALID-TOKEN", API_BASE_URL, is_valid=False, token_info=None)

    result = await cache.get("idt:TKN-INVALID-TOKEN", API_BASE_URL)

    assert result == (False, None)


async def test_cache_invalidate():
    cache = TokenValidationCache()
    await cache.set("idt:TKN-1234-5678-SECRET", API_BASE_URL, is_valid=True, token_info={})

    await cache.invalidate("idt:TKN-1234-5678-SECRET", API_BASE_URL)  # act

    assert await cache.get("idt:TKN-1234-5678-SECRET", API_BASE_URL) is None


async def test_cache_get_stats():
    cache = TokenValidationCache()
    await cache.set("idt:TKN-1234-5678-SECRET1", API_BASE_URL, is_valid=True, token_info={})
    await cache.set("idt:TKN-1234-5678-SECRET2", API_BASE_URL, is_valid=False, token_info=None)

    result = cache.get_stats()

    assert result == {
        "total_entries": 2,
        "valid_entries": 2,
        "expired_entries": 0,
        "ttl_minutes": 10,
    }


@pytest.mark.parametrize(
    ("token", "expected_token_id"),
    [
        ("idt:TKN-1234-5678:SECRET", "TKN-1234-5678"),
        ("Bearer idt:TKN-1234-5678:SECRET", "TKN-1234-5678"),
        ("idt:TKN-1234-5678", "TKN-1234-5678"),
        ("idt:IDT-USR-9999-8888:SECRET", None),  # user tokens are not API tokens
        ("TKN-1234-5678:SECRET", None),  # missing the idt: prefix
        ("INVALID-TOKEN", None),
        (
            "eyJhbGciOiJSUzI1NiJ9.eyJ1c2VyIjoiVVNSIn0.sig",
            None,
        ),  # JWTs are only read after verification
    ],
)
def test_parse_token_id(token, expected_token_id):
    result = parse_token_id(token)

    assert result == expected_token_id


def test_parse_jwt_claims_always_returns_none():
    result = parse_jwt_claims("header.payload.signature")

    assert result == (None, None)


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("Bearer idt:TKN-1234-5678:SECRET", "idt:TKN-1234-5678:SECRET"),
        ("bearer idt:TKN-X:Y", "idt:TKN-X:Y"),
        ("  idt:TKN-A:B  ", "idt:TKN-A:B"),
        ("  Bearer idt:TKN-A:B  ", "idt:TKN-A:B"),
        ("", ""),
        ("   ", ""),
        ("  Bearer   ", "Bearer"),  # only "Bearer " with a trailing space is a prefix
    ],
)
def test_normalize_token(token, expected):
    result = normalize_token(token)

    assert result == expected


async def test_validate_token_success():
    token = "idt:TKN-1234-5678:SECRET"
    api_base_url = "https://api.test.com"

    mock_response = {
        "id": "TKN-1234-5678",
        "status": "Active",
        "name": "Test Token",
        "account": {
            "id": "ACC-123-456",
            "name": "Test Account",
            "type": "Vendor",
        },
    }

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

        assert is_valid is True
        assert token_info == mock_response
        assert error is None


async def test_validate_token_inactive():
    token = "idt:TKN-1234-5678:SECRET"
    api_base_url = "https://api.test.com"

    mock_response = {
        "id": "TKN-1234-5678",
        "status": "Inactive",
        "name": "Inactive Token",
        "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
    }

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

        # Inactive tokens should be rejected even if API returns 200
        assert is_valid is False
        assert token_info == mock_response
        assert error is not None
        assert "not active" in error.lower()
        assert "Inactive" in error


async def test_validate_token_not_found():
    token = "idt:TKN-9999-9999:SECRET"
    api_base_url = "https://api.test.com"

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("404 Not Found"))
        mock_client_class.return_value.__aenter__.return_value = mock_client

        is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

        assert is_valid is False
        assert token_info is None
        assert "404" in error or "not found" in error.lower()


async def test_validate_token_unauthorized():
    token = "idt:TKN-8888-8888:SECRET"
    api_base_url = "https://api.test.com"

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("401 Unauthorized"))
        mock_client_class.return_value.__aenter__.return_value = mock_client

        is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

        assert is_valid is False
        assert token_info is None
        assert "401" in error or "unauthorized" in error.lower()


async def test_validate_token_uses_cache():
    token = "idt:TKN-5555-5555:SECRET"
    api_base_url = "https://api.test.com"

    mock_response = {
        "id": "TKN-5555-5555",
        "status": "Active",
        "name": "Test Token",
        "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
    }

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # First call - should hit API
        is_valid1, token_info1, _error1 = await validate_token(token, api_base_url, use_cache=True)
        assert is_valid1 is True
        assert mock_client.get.call_count == 1

        # Second call - should use cache
        is_valid2, token_info2, _error2 = await validate_token(token, api_base_url, use_cache=True)
        assert is_valid2 is True
        assert token_info2 == token_info1
        # Should still be 1 because cache was used
        assert mock_client.get.call_count == 1


async def test_validate_token_bypass_cache():
    token = "idt:TKN-6666-6666:SECRET"
    api_base_url = "https://api.test.com"

    mock_response = {
        "id": "TKN-6666-6666",
        "status": "Active",
        "name": "Test Token",
        "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
    }

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # First call
        await validate_token(token, api_base_url, use_cache=False)
        assert mock_client.get.call_count == 1

        # Second call with use_cache=False - should hit API again
        await validate_token(token, api_base_url, use_cache=False)
        assert mock_client.get.call_count == 2


async def test_validate_token_with_normalized_token():
    token = "idt:TKN-7777-7777:SECRET"
    api_base_url = "https://api.test.com"

    mock_response = {
        "id": "TKN-7777-7777",
        "status": "Active",
        "name": "Test Token",
        "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
    }

    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        is_valid, _token_info, _error = await validate_token(token, api_base_url, use_cache=False)

        assert is_valid is True
        assert mock_client.get.call_count == 1
        # API must be called with single "Bearer " prefix (middleware passes normalized token)
        call_args = mock_client.get.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer idt:TKN-7777-7777:SECRET"


async def test_validate_jwt_requires_jwks_url_or_iss():

    payload = {"https://claims.softwareone.com/userId": "USR-1234-5678"}  # no iss
    payload_json = json.dumps(payload).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode().rstrip("=")
    token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
    api_base_url = "https://api.test.com"

    with patch("mpt_mcp.token_validator.config") as mock_config:
        mock_config.jwt_jwks_url = ""

        is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

        assert is_valid is False
        assert token_info is None
        assert error is not None
        assert "JWT verification" in error or "JWT_JWKS_URL" in error or "iss" in error


@pytest.fixture
def issuer(request):
    # One issuer per test: the JWKS URL is derived from it and its keys are cached per URL
    slug = request.node.name.translate(SLUG_TRANSLATION)
    return f"https://{slug}.auth.test.com"


@pytest.fixture(scope="module")
def jwks(rsa_private_key):
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_private_key.public_key()))
    return {"keys": [{**public_jwk, "kid": "test-key", "alg": "RS256", "use": "sig"}]}


@pytest.fixture
def mock_auth_http(jwks):
    def _response(url, **kwargs):
        response = Mock(status_code=HTTPStatus.OK)
        payload = (
            mock_auth_http_state["jwks"]
            if url.endswith("/.well-known/jwks.json")
            else {"id": JWT_USER_ID, "status": "Active", "account": {"id": "ACC-1", "name": "Test"}}
        )
        response.json.return_value = payload
        return response

    mock_auth_http_state = {"jwks": jwks}
    client = AsyncMock()
    client.get = AsyncMock(side_effect=_response)
    client.jwks_state = mock_auth_http_state
    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = client
        yield client


@pytest.fixture(scope="module")
def other_private_key():
    return rsa.generate_private_key(public_exponent=RSA_PUBLIC_EXPONENT, key_size=RSA_KEY_SIZE)


@pytest.fixture(scope="module")
def rsa_private_key():
    return rsa.generate_private_key(public_exponent=RSA_PUBLIC_EXPONENT, key_size=RSA_KEY_SIZE)


@pytest.fixture
def sign_jwt(rsa_private_key, issuer):
    def _sign_jwt(claims, *, kid="test-key", private_key=None, algorithm="RS256"):
        headers = {"kid": kid} if kid else None
        full_claims = {
            "iss": issuer,
            "https://claims.softwareone.com/userId": JWT_USER_ID,
            **claims,
        }
        return jwt.encode(
            full_claims, private_key or rsa_private_key, algorithm=algorithm, headers=headers
        )

    return _sign_jwt


async def test_validate_jwt_within_exp_leeway_accepted(sign_jwt, mock_auth_http):
    now = int(time.time())
    token = sign_jwt({"exp": now - 60, "iat": now - ISSUED_SECONDS_AGO})

    is_valid, _, error = await validate_token(token, API_BASE_URL, use_cache=False)

    assert (is_valid, error) == (True, None)


async def test_validate_jwt_beyond_exp_leeway_rejected(sign_jwt, mock_auth_http):
    now = int(time.time())
    token = sign_jwt({"exp": now - EXPIRED_SECONDS_AGO, "iat": now - ISSUED_SECONDS_AGO})

    result = await validate_token(token, API_BASE_URL, use_cache=False)

    assert result == (False, None, "Token expired")


async def test_validate_jwt_exp_leeway_uses_config(sign_jwt, mock_auth_http):
    now = int(time.time())
    token = sign_jwt({"exp": now - EXPIRED_SECONDS_AGO, "iat": now - ISSUED_SECONDS_AGO})

    with patch.object(config, "jwt_exp_leeway_seconds", WIDE_LEEWAY_SECONDS):
        is_valid, _, error = await validate_token(token, API_BASE_URL, use_cache=False)

    assert (is_valid, error) == (True, None)


async def test_validate_jwt_without_exp_accepted(sign_jwt, mock_auth_http):
    token = sign_jwt({"iat": int(time.time()) - 60})

    is_valid, _, error = await validate_token(token, API_BASE_URL, use_cache=False)

    assert (is_valid, error) == (True, None)


async def test_validate_jwt_without_kid_tries_every_key(
    sign_jwt, jwks, other_private_key, mock_auth_http
):
    other_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(other_private_key.public_key()))
    other_key = {**other_jwk, "kid": "other-key"}
    mock_auth_http.jwks_state["jwks"] = {"keys": [other_key, *jwks["keys"]]}
    token = sign_jwt({}, kid=None)

    is_valid, _, error = await validate_token(token, API_BASE_URL, use_cache=False)

    assert (is_valid, error) == (True, None)


async def test_validate_jwt_rejects_unknown_key(sign_jwt, other_private_key, mock_auth_http):
    token = sign_jwt({}, private_key=other_private_key)

    result = await validate_token(token, API_BASE_URL, use_cache=False)

    assert result == (False, None, "JWT signature or claims invalid")


@pytest.mark.parametrize(
    "sign_kwargs",
    [
        {"kid": "missing-key"},
        {"private_key": "a-shared-secret-of-at-least-32-bytes", "algorithm": "HS256"},
    ],
    ids=["unknown-kid", "hs256"],
)
async def test_validate_jwt_rejects_untrusted_header(sign_jwt, mock_auth_http, sign_kwargs):
    token = sign_jwt({}, **sign_kwargs)

    result = await validate_token(token, API_BASE_URL, use_cache=False)

    assert result == (False, None, "JWT signature or claims invalid")


async def test_validate_jwt_rejects_on_jwks_failure(sign_jwt, mock_auth_http):
    mock_auth_http.get.side_effect = httpx.ConnectError("JWKS unreachable")
    token = sign_jwt({})

    result = await validate_token(token, API_BASE_URL, use_cache=False)

    assert result == (False, None, "JWT signature or claims invalid")
