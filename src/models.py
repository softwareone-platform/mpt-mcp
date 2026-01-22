"""
Pydantic models for type safety and validation
"""

from typing import Any

from pydantic import BaseModel, Field


class APIResponse(BaseModel):
    """Standard API response model"""

    success: bool
    data: Any | None = None
    error: str | None = None
    message: str | None = None


class EndpointInfo(BaseModel):
    """Information about an API endpoint"""

    method: str
    path: str
    summary: str
    description: str | None = None
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    responses: dict[str, Any] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    """Tool execution request"""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    """Tool execution response"""

    success: bool
    data: Any | None = None
    error: str | None = None


class CallToolResponse(BaseModel):
    """Tool call response (compatible with MCP)"""

    content: list[dict[str, Any]]
    is_error: bool = False
