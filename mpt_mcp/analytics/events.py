from dataclasses import asdict, dataclass
from http import HTTPStatus
from typing import Any, ClassVar, override

ERROR_EVENT_TYPE = "error"


@dataclass(frozen=True, kw_only=True)
class AnalyticsContext:
    """Caller of the MCP request, stored with each of its events."""

    token_id: str | None = None
    api_endpoint: str | None = None
    client_info: str | None = None
    client_ip: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class McpEvent:
    """Event of one MCP call; each field is a column of mcp_events."""

    # Name of the event in the console logs
    log_label: ClassVar[str]
    # event_type of the event when it succeeds; a failed event is stored as "error"
    success_type: ClassVar[str]

    response_time_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def elapsed_ms(self) -> int | None:
        """Time the call took, in milliseconds."""
        return self.response_time_ms

    @property
    def event_type(self) -> str:
        """Event type stored in mcp_events."""
        return self.success_type if self.failure is None else ERROR_EVENT_TYPE

    @property
    def failure(self) -> str | None:
        """Why the call failed, or None when it succeeded."""
        return self.error_message

    @property
    def subject(self) -> str:
        """What the call was about: tool, prompt, resource URI or API resource."""
        raise NotImplementedError

    def to_row(self) -> dict[str, Any]:
        """Return the mcp_events columns of the event, without the caller's context."""
        return {**asdict(self), "event_type": self.event_type}


@dataclass(frozen=True, kw_only=True)
class ToolCallEvent(McpEvent):
    """Call of an MCP tool."""

    log_label: ClassVar[str] = "Tool"
    success_type: ClassVar[str] = "tool_call"

    tool_name: str

    @property
    @override
    def subject(self) -> str:
        """Name of the tool."""
        return self.tool_name


@dataclass(frozen=True, kw_only=True)
class PromptGetEvent(McpEvent):
    """Get of an MCP prompt, stored with the prompt name in tool_name."""

    log_label: ClassVar[str] = "Prompt"
    success_type: ClassVar[str] = "prompt_get"

    tool_name: str

    @property
    @override
    def subject(self) -> str:
        """Name of the prompt."""
        return self.tool_name


@dataclass(frozen=True, kw_only=True)
class ResourceReadEvent(McpEvent):
    """Read of an MCP resource."""

    log_label: ClassVar[str] = "Resource"
    success_type: ClassVar[str] = "resource_read"

    resource_uri: str

    @property
    @override
    def subject(self) -> str:
        """URI of the resource."""
        return self.resource_uri


@dataclass(frozen=True, kw_only=True)
class ApiQueryEvent(McpEvent):
    """Marketplace API request of marketplace_query; it keeps its type when the API fails."""

    log_label: ClassVar[str] = "API"
    success_type: ClassVar[str] = "api_query"

    api_resource: str
    api_path: str
    api_status_code: int
    api_response_time_ms: int
    api_method: str = "GET"
    tool_name: str = "marketplace_query"
    result_count: int | None = None
    rql_filter: str | None = None
    limit_value: int | None = None
    offset_value: int | None = None
    order_by: str | None = None
    select_fields: str | None = None

    @property
    @override
    def elapsed_ms(self) -> int:
        """Time the API took to answer, in milliseconds."""
        return self.api_response_time_ms

    @property
    @override
    def event_type(self) -> str:
        """Event type stored in mcp_events, api_query also when the API fails."""
        return self.success_type

    @property
    @override
    def failure(self) -> str | None:
        """The status code when the API did not answer with a 2xx."""
        if HTTPStatus.OK <= self.api_status_code < HTTPStatus.MULTIPLE_CHOICES:
            return None

        return str(self.api_status_code)

    @property
    @override
    def subject(self) -> str:
        """Name of the API resource."""
        return self.api_resource
