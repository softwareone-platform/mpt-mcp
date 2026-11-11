from typing import Any

from pydantic import Field

from mpt_mcp.tools.responses.base import ToolResponse, optional_field


class SpecCacheInfo(ToolResponse):
    """State of the OpenAPI spec cache on disk."""

    cache_directory: str = Field(description="Directory of the cache files")
    total_entries: int = Field(description="Cached specs")
    valid_entries: int = Field(description="Cached specs younger than the TTL")
    expired_entries: int = Field(description="Cached specs older than the TTL")
    total_size_bytes: int = Field(description="Size of the cache files")
    ttl_hours: float = Field(description="Time a cached spec stays valid")


class CacheInfoResponse(ToolResponse):
    """State of the OpenAPI spec cache."""

    cache_status: str = Field(description="Whether the cache is enabled")
    cache_info: SpecCacheInfo = Field(description="State of the cache on disk")
    note: str = Field(description="What the cache is for")


class RefreshCacheResponse(ToolResponse):
    """Result of reloading the OpenAPI spec."""

    success: bool = Field(description="Whether the spec was reloaded, always true")
    message: str = Field(description="Result of the refresh")
    endpoints_count: int = Field(description="Resources found in the reloaded spec")


class DocumentationCacheState(ToolResponse):
    """State of the documentation cache."""

    enabled: bool = Field(description="Whether GitBook is configured")
    total_pages: int = Field(description="Pages in the cache")
    cache_info: dict[str, Any] | None = optional_field("Refresh state of the cache")


class TokenCacheState(ToolResponse):
    """State of the token validation cache."""

    enabled: bool = Field(description="Whether the cache is available")
    cache_stats: dict[str, Any] | None = optional_field("Cached validations and their TTL")
    description: str | None = optional_field("What the cache is for")
    error: str | None = optional_field("Why the cache is not available")


class ResourcesInfoResponse(ToolResponse):
    """State of the documentation and token validation caches."""

    documentation: DocumentationCacheState = Field(description="Documentation cache")
    token_validation: TokenCacheState = Field(description="Token validation cache")
