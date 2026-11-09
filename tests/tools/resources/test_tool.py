import json
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

from mpt_mcp.tools.resources.tool import (
    marketplace_audit_fields,
    marketplace_resource_info,
    marketplace_resource_schema,
    marketplace_resources,
)


@pytest.fixture
def audit_fields_loader():
    with patch("mpt_mcp.tools.resources.tool.get_audit_fields") as get_audit_fields:
        yield get_audit_fields


@pytest.mark.parametrize("tool", [marketplace_resource_info, marketplace_resource_schema])
def test_unknown_resource_suggests_similar(spec_factory, tool):
    with pytest.raises(ToolError, match=r"Unknown resource: 'commerce\.order'") as error:
        tool("commerce.order", spec=spec_factory())

    _, error_details = str(error.value).split("\n", 1)
    details = json.loads(error_details)
    assert details["did_you_mean"][0] == "commerce.orders"
    assert details["available_categories"] == ["catalog", "commerce"]


def test_resources_shows_caller(call_context, spec_factory):
    registry = {"commerce.orders": {"path": "/public/v1/commerce/orders", "summary": "Orders"}}

    result = marketplace_resources(
        call_context=call_context, spec=spec_factory(registry=registry)
    ).model_dump()

    assert (result["api_endpoint"], result["user"]) == ("https://api.test.com", "TKN-1234-5678")
    assert result["categories"] == {
        "commerce": [{"resource": "commerce.orders", "summary": "Orders"}]
    }


def test_resource_info_describes_resource(spec_factory):
    result = marketplace_resource_info("commerce.orders", spec=spec_factory()).model_dump()

    assert (result["path"], result["summary"]) == ("/public/v1/commerce/orders", "List orders")


def test_resource_schema_describes_response(spec_factory, openapi_spec):
    result = marketplace_resource_schema(
        "commerce.orders", spec=spec_factory(openapi_spec=openapi_spec)
    ).model_dump()

    assert list(result["fields"]) == ["id", "status", "audit"]


def test_audit_fields_returns_events(spec_factory, audit_fields_loader):
    audit_fields_loader.return_value = {"resource": "commerce.orders", "events": ["created"]}

    result = marketplace_audit_fields("commerce.orders", spec=spec_factory()).model_dump()

    assert result == {"resource": "commerce.orders", "events": ["created"]}
    audit_fields_loader.assert_called_once_with("https://api.test.com", "commerce.orders")


def test_audit_fields_reports_error(spec_factory, audit_fields_loader):
    audit_fields_loader.return_value = {"error": "No audit fields", "hint": "Load the spec"}

    with pytest.raises(ToolError, match="No audit fields") as error:
        marketplace_audit_fields("commerce.orders", spec=spec_factory())

    _, error_details = str(error.value).split("\n", 1)
    assert json.loads(error_details) == {"hint": "Load the spec"}
