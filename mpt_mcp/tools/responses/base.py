from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def optional_field(description: str, alias: str | None = None) -> Any:
    """
    Declare an optional response field that is left out of the response when it has no value.

    Args:
        description: Field description sent to MCP clients in the tool's output schema
        alias: Name of the field in the response, when it is not a valid Python name

    Returns:
        Pydantic field that defaults to None and is not serialized while it is None
    """
    return Field(
        None,
        alias=alias,
        description=description,
        exclude_if=lambda field_value: field_value is None,
    )


class ToolResponse(BaseModel):
    """Base of the tool responses: keys the model does not declare are kept as they are."""

    model_config = ConfigDict(
        extra="allow", serialize_by_alias=True, validate_by_alias=True, validate_by_name=True
    )
