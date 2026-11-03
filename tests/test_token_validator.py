import base64
import json
import logging
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
API_TOKEN = "idt:TKN-1234-5678:SECRET"
EXPIRED_SECONDS_AGO = 200  # beyond the default 120 s leeway
ISSUED_SECONDS_AGO = 3600
JWT_USER_ID = "USR-1234-5678"
RSA_KEY_SIZE = 2048
RSA_PUBLIC_EXPONENT = 65537
SLUG_TRANSLATION = str.maketrans({"_": "-", "[": "-", "]": None})
TOKEN_CACHE_TTL_MINUTES = 30
WIDE_LEEWAY_SECONDS = 300


@pytest.fixture
def token_details():
    return {
        "id": "TKN-1234-5678",
        "status": "Active",
        "name": "Test Token",
        "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
    }


@pytest.fixture
def token_api(token_details):
    response = Mock(spec=httpx.Response, status_code=HTTPStatus.OK)
    response.json.return_value = token_details
    client = AsyncMock(spec=httpx.AsyncClient, get=AsyncMock(return_value=response))
    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = client
        yield client


@pytest.fixture
def issuer(request):
    slug = request.node.name.translate(SLUG_TRANSLATION)
    return f"https://{slug}.auth.test.com"


@pytest.fixture(scope="module")
def jwks(rsa_private_key):
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_private_key.public_key()))
    return {"keys": [{**public_jwk, "kid": "test-key", "alg": "RS256", "use": "sig"}]}


@pytest.fixture
def jwks_state(jwks):
    return {"jwks": jwks}


@pytest.fixture
def auth_response_factory(jwks_state):
    def factory(url, **kwargs):
        response = Mock(spec=httpx.Response, status_code=HTTPStatus.OK)
        response.json.return_value = (
            jwks_state["jwks"]
            if url.endswith("/.well-known/jwks.json")
            else {"id": JWT_USER_ID, "status": "Active", "account": {"id": "ACC-1", "name": "Test"}}
        )
        return response

    return factory


@pytest.fixture
def mock_auth_http(jwks_state, auth_response_factory):
    client = AsyncMock(
        spec=httpx.AsyncClient,
        get=AsyncMock(side_effect=auth_response_factory),
        jwks_state=jwks_state,
    )
    with patch("mpt_mcp.token_validator.httpx.AsyncClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = client
        yield client


@pytest.fixture(scope="module")
def rsa_key_factory():
    def factory():
        return rsa.generate_private_key(public_exponent=RSA_PUBLIC_EXPONENT, key_size=RSA_KEY_SIZE)

    return factory


@pytest.fixture(scope="module")
def rsa_private_key(rsa_key_factory):
    return rsa_key_factory()


@pytest.fixture
def jwt_factory(rsa_private_key, issuer):
    def factory(claims, *, kid="test-key", private_key=None, algorithm="RS256"):
        headers = {"kid": kid} if kid else None
        full_claims = {
            "iss": issuer,
            "https://claims.softwareone.com/userId": JWT_USER_ID,
            **claims,
        }
        return jwt.encode(
            full_claims, private_key or rsa_private_key, algorithm=algorithm, headers=headers
        )

    return factory


@pytest.fixture
def validate_jwt(jwt_factory, mock_auth_http):
    async def factory(claims, **sign_kwargs):
        return await validate_token(
            jwt_factory(claims, **sign_kwargs), API_BASE_URL, use_cache=False
        )

    return factory


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


async def test_validate_token_success(token_api, token_details):
    result = await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)

    assert result == (True, token_details, None)


async def test_validate_token_logs_one_line(token_api, caplog):
    with caplog.at_level(logging.INFO, logger="mpt_mcp.token_validator"):
        await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)  # act

    expected = (
        "Token TKN-1234-5678 validated: account Test Account (ACC-123-456), type Vendor, "
        "status Active"
    )
    assert expected in caplog.messages
    assert "Test Token" not in caplog.text


async def test_validate_token_inactive(token_api, token_details):
    token_details["status"] = "Inactive"

    result = await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)

    assert result == (False, token_details, "Token exists but is not active (status: Inactive)")


@pytest.mark.parametrize("api_error", ["404 Not Found", "401 Unauthorized"])
async def test_validate_token_api_error(token_api, api_error):
    token_api.get.side_effect = Exception(api_error)

    result = await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)

    is_valid, token_info, error = result
    assert (is_valid, token_info) == (False, None)
    assert api_error in error


async def test_validate_token_uses_cache(token_api):
    token = "idt:TKN-5555-5555:SECRET"
    first_result = await validate_token(token, API_BASE_URL, use_cache=True)

    result = await validate_token(token, API_BASE_URL, use_cache=True)

    assert result == first_result
    assert token_api.get.call_count == 1


async def test_validate_token_bypass_cache(token_api):
    await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)

    await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)  # act

    assert token_api.get.call_count == 2


async def test_validate_token_sends_bearer_prefix(token_api):
    await validate_token(API_TOKEN, API_BASE_URL, use_cache=False)  # act

    assert token_api.get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {API_TOKEN}"


async def test_validate_jwt_requires_jwks_url_or_iss(monkeypatch):
    payload = {"https://claims.softwareone.com/userId": "USR-1234-5678"}
    payload_json = json.dumps(payload).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode().rstrip("=")
    token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
    monkeypatch.setattr(config, "jwt_jwks_url", "")

    result = await validate_token(token, "https://api.test.com", use_cache=False)

    assert result == (
        False,
        None,
        "JWT verification required. Set JWT_JWKS_URL or use a token with iss claim (e.g. Auth0).",
    )


async def test_validate_jwt_within_exp_leeway_accepted(validate_jwt):
    now = int(time.time())
    claims = {"exp": now - 60, "iat": now - ISSUED_SECONDS_AGO}

    result = await validate_jwt(claims)

    is_valid, _, error = result
    assert (is_valid, error) == (True, None)


async def test_validate_jwt_beyond_exp_leeway_rejected(validate_jwt):
    now = int(time.time())

    result = await validate_jwt({"exp": now - EXPIRED_SECONDS_AGO, "iat": now - ISSUED_SECONDS_AGO})

    assert result == (False, None, "Token expired")


async def test_validate_jwt_exp_leeway_uses_config(validate_jwt):
    now = int(time.time())
    claims = {"exp": now - EXPIRED_SECONDS_AGO, "iat": now - ISSUED_SECONDS_AGO}

    with patch.object(config, "jwt_exp_leeway_seconds", WIDE_LEEWAY_SECONDS):
        result = await validate_jwt(claims)

    is_valid, _, error = result
    assert (is_valid, error) == (True, None)


async def test_validate_jwt_without_exp_accepted(validate_jwt):
    claims = {"iat": int(time.time()) - 60}

    result = await validate_jwt(claims)

    is_valid, _, error = result
    assert (is_valid, error) == (True, None)


async def test_validate_jwt_without_kid_tries_every_key(
    validate_jwt, jwks, rsa_key_factory, mock_auth_http
):
    other_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key_factory().public_key()))
    other_key = {**other_jwk, "kid": "other-key"}
    mock_auth_http.jwks_state["jwks"] = {"keys": [other_key, *jwks["keys"]]}

    result = await validate_jwt({}, kid=None)

    is_valid, _, error = result
    assert (is_valid, error) == (True, None)


async def test_validate_jwt_rejects_unknown_key(validate_jwt, rsa_key_factory):
    other_private_key = rsa_key_factory()

    result = await validate_jwt({}, private_key=other_private_key)

    assert result == (False, None, "JWT signature or claims invalid")


@pytest.mark.parametrize(
    "sign_kwargs",
    [
        {"kid": "missing-key"},
        {"private_key": "a-shared-secret-of-at-least-32-bytes", "algorithm": "HS256"},
    ],
    ids=["unknown-kid", "hs256"],
)
async def test_validate_jwt_rejects_untrusted_header(validate_jwt, sign_kwargs):
    result = await validate_jwt({}, **sign_kwargs)

    assert result == (False, None, "JWT signature or claims invalid")


async def test_validate_jwt_rejects_on_jwks_failure(validate_jwt, mock_auth_http):
    mock_auth_http.get.side_effect = httpx.ConnectError("JWKS unreachable")

    result = await validate_jwt({})

    assert result == (False, None, "JWT signature or claims invalid")
