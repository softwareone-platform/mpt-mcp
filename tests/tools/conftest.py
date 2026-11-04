from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from mpt_mcp.auth.call_context import CallContext
from mpt_mcp.marketplace.api_client import APIClient
from mpt_mcp.marketplace.audit_fields import FALLBACK_STATIC_REGEX
from mpt_mcp.tools.dependencies import MarketplaceSpec
from mpt_mcp.tools.query.params import DEFAULT_LIMIT, QueryParams


@pytest.fixture
def endpoints_registry():
    return {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "method": "GET",
        },
        "commerce.orders": {
            "path": "/public/v1/commerce/orders",
            "method": "GET",
            "summary": "List orders",
            "description": "Get a list of orders",
            "parameters": [],
        },
    }


@pytest.fixture
def openapi_spec():
    return {
        "paths": {
            "/public/v1/commerce/orders": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "string"},
                                                        "status": {"type": "string"},
                                                        "audit": {"type": "object"},
                                                    },
                                                },
                                            },
                                            "$meta": {"type": "object"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }


@pytest.fixture
def openapi_spec_factory():
    def factory(fields):
        item_schema = {
            "type": "object",
            "properties": {field: {"type": "string"} for field in fields},
        }
        list_schema = {
            "type": "object",
            "properties": {"data": {"type": "array", "items": item_schema}},
        }
        response = {"200": {"content": {"application/json": {"schema": list_schema}}}}
        return {"paths": {"/public/v1/commerce/orders": {"get": {"responses": response}}}}

    return factory


@pytest.fixture
def call_context():
    return CallContext(endpoint="https://api.test.com", token="idt:TKN-1234-5678:SECRET")


@pytest.fixture
def patched_api_client():
    client = Mock(spec=APIClient, base_url="https://api.test.com")
    with patch.object(
        CallContext, "create_api_client", new_callable=AsyncMock, return_value=client
    ):
        yield client


@pytest.fixture
def query_params_factory():
    def factory(**query_args):
        return QueryParams(
            **{"limit": DEFAULT_LIMIT, "offset": None, "order": None, "rql": "", "select": None}
            | query_args
        )

    return factory


@pytest.fixture
def spec_factory(endpoints_registry):
    def factory(registry=None, openapi_spec=None):
        return MarketplaceSpec(
            api_base_url="https://api.test.com",
            audit_regex=FALLBACK_STATIC_REGEX,
            endpoints_registry=endpoints_registry if registry is None else registry,
            openapi_spec=openapi_spec or {},
        )

    return factory


@pytest.fixture
def http_error_factory():
    def factory(status, response_body):
        mock_response = Mock(spec=httpx.Response, status_code=status, text=status.phrase)
        if isinstance(response_body, Exception):
            mock_response.json.side_effect = response_body
        else:
            mock_response.json.return_value = response_body
        mock_request = Mock(
            spec=httpx.Request, url="https://api.test.com/public/v1/catalog/products"
        )
        return httpx.HTTPStatusError(
            f"{status.value} {status.phrase}", request=mock_request, response=mock_response
        )

    return factory
