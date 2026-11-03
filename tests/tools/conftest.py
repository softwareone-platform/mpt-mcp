from unittest.mock import AsyncMock, Mock, patch

import pytest

from mpt_mcp.api_client import APIClient
from mpt_mcp.call_context import CallContext


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
def registry_loader():
    with patch(
        "mpt_mcp.endpoint_registry.get_endpoints_registry", new_callable=AsyncMock
    ) as get_endpoints_registry:
        yield get_endpoints_registry


@pytest.fixture
def patched_api_client():
    client = Mock(spec=APIClient, base_url="https://api.test.com")
    with patch.object(
        CallContext, "create_api_client", new_callable=AsyncMock, return_value=client
    ):
        yield client
