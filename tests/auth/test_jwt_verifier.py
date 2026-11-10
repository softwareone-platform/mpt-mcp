import base64
import json
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.auth.jwt_verifier import JwtVerifier
from mpt_mcp.config import config

JWKS_URL = "https://issuer.test.com/.well-known/jwks.json"


@pytest.fixture
def jwt_verifier():
    return JwtVerifier()


@pytest.fixture
def jwks():
    return {"keys": [{"kty": "RSA", "kid": "test-key"}]}


@pytest.fixture
def jwks_response(jwks):
    response = Mock(spec=httpx.Response, status_code=HTTPStatus.OK)
    response.json.return_value = jwks
    return response


@pytest.fixture
def jwks_client(jwks_response):
    client = AsyncMock(spec=httpx.AsyncClient, get=AsyncMock(return_value=jwks_response))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client_class.return_value.__aenter__.return_value = client
        yield client


@pytest.fixture
def token_factory():
    def factory(payload_segment):
        return f"eyJhbGciOiJSUzI1NiJ9.{payload_segment}.signature"

    return factory


@pytest.fixture
def claims_token_factory(token_factory):
    def factory(claims):
        encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
        return token_factory(encoded.rstrip("="))

    return factory


@pytest.fixture(autouse=True)
def no_configured_jwks_url(monkeypatch):
    monkeypatch.setattr(config, "jwt_jwks_url", "")


def test_extract_claims(jwt_verifier):
    payload = {
        "https://claims.softwareone.com/userId": "USR-1234-5678",
        "https://claims.softwareone.com/accountId": "ACC-1234-5678",
    }

    result = jwt_verifier.extract_claims(payload)

    assert result == ("USR-1234-5678", "ACC-1234-5678")


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {
            "https://claims.softwareone.com/userId": "TKN-1234",
            "https://claims.softwareone.com/accountId": 1234,
        },
    ],
)
def test_extract_claims_ignores_invalid_ids(jwt_verifier, claims):
    result = jwt_verifier.extract_claims(claims)

    assert result == (None, None)


def test_find_jwks_url_from_issuer(jwt_verifier, claims_token_factory):
    token = claims_token_factory({"iss": " https://issuer.test.com/ "})

    result = jwt_verifier.find_jwks_url(token)

    assert result == JWKS_URL


def test_find_jwks_url_configured(jwt_verifier, claims_token_factory, monkeypatch):
    monkeypatch.setattr(config, "jwt_jwks_url", "https://configured.test.com/jwks.json")
    token = claims_token_factory({"iss": "https://issuer.test.com"})

    result = jwt_verifier.find_jwks_url(token)

    assert result == "https://configured.test.com/jwks.json"


@pytest.mark.parametrize(
    "claims",
    [{"iss": "http://issuer.test.com"}, {"iss": 1234}, {}],
)
def test_find_jwks_url_without_https_issuer(jwt_verifier, claims_token_factory, claims):
    token = claims_token_factory(claims)

    result = jwt_verifier.find_jwks_url(token)

    assert result is None


@pytest.mark.parametrize("payload_segment", ["not-base64!", "WyJsaXN0Il0"])
def test_find_jwks_url_unreadable_payload(jwt_verifier, token_factory, payload_segment):
    token = token_factory(payload_segment)

    result = jwt_verifier.find_jwks_url(token)

    assert result is None


def test_find_jwks_url_not_a_jwt(jwt_verifier):
    result = jwt_verifier.find_jwks_url("not.a-jwt")

    assert result is None


async def test_load_jwks_cached(jwt_verifier, jwks_client, jwks):
    await jwt_verifier.load_jwks(JWKS_URL)

    result = await jwt_verifier.load_jwks(JWKS_URL)

    assert result == jwks
    jwks_client.get.assert_awaited_once_with(JWKS_URL)


async def test_load_jwks_invalid_json(jwt_verifier, jwks_client, jwks_response):
    jwks_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)

    result = await jwt_verifier.load_jwks(JWKS_URL)

    assert result is None


@pytest.mark.parametrize("jwks_body", [["keys"], {"no_keys": []}])
async def test_load_jwks_invalid_format(jwt_verifier, jwks_client, jwks_response, jwks_body):
    jwks_response.json.return_value = jwks_body

    result = await jwt_verifier.load_jwks(JWKS_URL)

    assert result is None


async def test_load_jwks_http_error(jwt_verifier, jwks_client, jwks_response):
    request = httpx.Request("GET", JWKS_URL)
    jwks_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not found", request=request, response=httpx.Response(HTTPStatus.NOT_FOUND)
    )

    result = await jwt_verifier.load_jwks(JWKS_URL)

    assert result is None
