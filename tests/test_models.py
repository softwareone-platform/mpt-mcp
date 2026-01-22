"""Tests for data models."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    APIResponse,
    CallToolResponse,
    EndpointInfo,
    ToolRequest,
    ToolResponse,
)


class TestAPIResponse:
    """Test APIResponse model."""

    def test_api_response_success(self):
        """Test successful APIResponse."""
        response = APIResponse(success=True, data={"id": "1", "name": "Test"}, error=None, message="Success")

        assert response.success is True
        assert response.data["id"] == "1"
        assert response.error is None
        assert response.message == "Success"

    def test_api_response_error(self):
        """Test error APIResponse."""
        response = APIResponse(success=False, data=None, error="Not found", message="Resource not found")

        assert response.success is False
        assert response.data is None
        assert response.error == "Not found"
        assert response.message == "Resource not found"

    def test_api_response_minimal(self):
        """Test APIResponse with minimal fields."""
        response = APIResponse(success=True)

        assert response.success is True
        assert response.data is None
        assert response.error is None
        assert response.message is None


class TestEndpointInfo:
    """Test EndpointInfo model."""

    def test_endpoint_info_creation(self):
        """Test creating an EndpointInfo instance."""
        endpoint = EndpointInfo(
            method="GET",
            path="/public/v1/catalog/products",
            summary="List all products",
            description="Returns a paginated list of products",
            parameters=[{"name": "limit", "type": "integer"}],
            responses={"200": {"description": "Success"}},
        )

        assert endpoint.method == "GET"
        assert endpoint.path == "/public/v1/catalog/products"
        assert endpoint.summary == "List all products"
        assert endpoint.description == "Returns a paginated list of products"
        assert len(endpoint.parameters) == 1
        assert endpoint.parameters[0]["name"] == "limit"
        assert "200" in endpoint.responses

    def test_endpoint_info_minimal(self):
        """Test EndpointInfo with minimal fields."""
        endpoint = EndpointInfo(method="POST", path="/test", summary="Test endpoint")

        assert endpoint.method == "POST"
        assert endpoint.path == "/test"
        assert endpoint.summary == "Test endpoint"
        assert endpoint.description is None
        assert endpoint.parameters == []
        assert endpoint.responses == {}

    def test_endpoint_info_default_factory(self):
        """Test EndpointInfo default factory fields."""
        endpoint = EndpointInfo(method="GET", path="/test", summary="Test")

        assert isinstance(endpoint.parameters, list)
        assert isinstance(endpoint.responses, dict)
        assert len(endpoint.parameters) == 0
        assert len(endpoint.responses) == 0


class TestToolRequest:
    """Test ToolRequest model."""

    def test_tool_request_creation(self):
        """Test creating a ToolRequest instance."""
        request = ToolRequest(tool_name="marketplace_query", arguments={"resource": "catalog.products", "limit": 10})

        assert request.tool_name == "marketplace_query"
        assert request.arguments["resource"] == "catalog.products"
        assert request.arguments["limit"] == 10

    def test_tool_request_minimal(self):
        """Test ToolRequest with minimal fields."""
        request = ToolRequest(tool_name="marketplace_resources")

        assert request.tool_name == "marketplace_resources"
        assert request.arguments == {}

    def test_tool_request_default_factory(self):
        """Test ToolRequest default factory for arguments."""
        request = ToolRequest(tool_name="test_tool")

        assert isinstance(request.arguments, dict)
        assert len(request.arguments) == 0


class TestToolResponse:
    """Test ToolResponse model."""

    def test_tool_response_success(self):
        """Test successful ToolResponse."""
        response = ToolResponse(success=True, data={"result": "success"}, error=None)

        assert response.success is True
        assert response.data["result"] == "success"
        assert response.error is None

    def test_tool_response_error(self):
        """Test error ToolResponse."""
        response = ToolResponse(success=False, data=None, error="Tool execution failed")

        assert response.success is False
        assert response.data is None
        assert response.error == "Tool execution failed"

    def test_tool_response_minimal(self):
        """Test ToolResponse with minimal fields."""
        response = ToolResponse(success=True)

        assert response.success is True
        assert response.data is None
        assert response.error is None


class TestCallToolResponse:
    """Test CallToolResponse model."""

    def test_call_tool_response_success(self):
        """Test successful CallToolResponse."""
        response = CallToolResponse(content=[{"type": "text", "text": "Success"}], is_error=False)

        assert len(response.content) == 1
        assert response.content[0]["type"] == "text"
        assert response.content[0]["text"] == "Success"
        assert response.is_error is False

    def test_call_tool_response_error(self):
        """Test error CallToolResponse."""
        response = CallToolResponse(content=[{"type": "text", "text": "Error occurred"}], is_error=True)

        assert len(response.content) == 1
        assert response.content[0]["text"] == "Error occurred"
        assert response.is_error is True

    def test_call_tool_response_default_is_error(self):
        """Test CallToolResponse default is_error value."""
        response = CallToolResponse(content=[{"type": "text", "text": "Test"}])

        assert response.is_error is False

    def test_call_tool_response_multiple_content(self):
        """Test CallToolResponse with multiple content items."""
        response = CallToolResponse(content=[{"type": "text", "text": "First"}, {"type": "text", "text": "Second"}])

        assert len(response.content) == 2
        assert response.content[0]["text"] == "First"
        assert response.content[1]["text"] == "Second"
