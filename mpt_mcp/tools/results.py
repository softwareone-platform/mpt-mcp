import json
import logging
from typing import Any

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

KEY_META = "$meta"
# Characters of a tool result: long results fill the model's context, and some MCP clients reject
# them. Results that may be longer are cut or come in parts
CHARACTER_LIMIT = 25_000
TRUNCATION_NOTE_CHARACTERS = 400
AUTH_HEADER_HINT = (
    "Provide your API token in the X-MPT-Authorization header (HTTP) or in "
    "MARKETPLACE_API_TOKEN (stdio)"
)
OPENAPI_SPEC_LOAD_ERROR = "Failed to load OpenAPI spec"


def tool_error(message: str, **details: Any) -> ToolError:
    """
    Build a tool error that carries its hints, so MCP clients mark the result as an error.

    Args:
        message: What failed
        details: Hints for the caller, such as an example or similar resources

    Returns:
        Tool error with the message followed by the hints as JSON; the message is kept on one
        line, so the hints are always the second line
    """
    if not details:
        return ToolError(message)

    one_line_message = " ".join(message.split())
    return ToolError(f"{one_line_message}\n{json.dumps(details, default=str)}")


def cut_text_to_budget(text: str, offset: int) -> tuple[str, int | None]:
    """
    Cut a text from offset to at most CHARACTER_LIMIT, at the end of a line when possible.

    Args:
        text: Full text
        offset: Character to start from

    Returns:
        The cut text, and the offset of the rest, or None when the text ends in this part

    Raises:
        ToolError: The offset is outside the text
    """
    if offset < 0 or (offset > 0 and offset >= len(text)):
        raise tool_error(
            f"offset {offset} is outside the page ({len(text)} characters)",
            hint="Read the page from offset=0",
        )

    end = offset + CHARACTER_LIMIT
    if end >= len(text):
        return text[offset:], None

    # Cut after the last line break, unless it would leave less than half of the budget
    line_end = text.rfind("\n", offset, end)
    if line_end > offset + CHARACTER_LIMIT // 2:
        end = line_end + 1
    return text[offset:end], end


def fit_result_to_budget(result: Any) -> Any:  # noqa: WPS210
    """
    Cut a page of items to the ones that fit in CHARACTER_LIMIT.

    A cut page says in $meta.truncated how many items the API returned and the limit that fits,
    so the caller can page on instead of getting a result its MCP client rejects;
    add_page_position gives the offset to continue with.

    Args:
        result: Marketplace API response

    Returns:
        The response, with only the items that fit when it is too long

    Raises:
        ToolError: Not even the first item of the page fits
    """
    page_items = result.get("data") if isinstance(result, dict) else None
    if not isinstance(page_items, list):
        return result
    if len(json.dumps(result, default=str)) <= CHARACTER_LIMIT:
        return result

    used_characters = len(json.dumps({**result, "data": []}, default=str))
    used_characters += TRUNCATION_NOTE_CHARACTERS
    kept_items: list[Any] = []
    for page_item in page_items:
        used_characters += len(json.dumps(page_item, default=str)) + 1
        if used_characters > CHARACTER_LIMIT:
            break
        kept_items.append(page_item)

    if not kept_items:
        raise tool_error(
            f"One item takes more than {CHARACTER_LIMIT} characters",
            hint="Return only the fields you need: select=-*,+id,+name",
        )

    kept_count = len(kept_items)
    logger.info(
        "Cut the page to %s of %s items to fit the result size", kept_count, len(page_items)
    )
    meta = result.get(KEY_META) or {}
    truncated = {
        "requested": len(page_items),
        "suggested_limit": kept_count,
        "hint": (
            "The page was cut to fit the result size limit. Continue with "
            f"$meta.pagination.next_offset; to fetch pages in parallel use limit={kept_count}, "
            "or return only the fields you need (select=-*,+id,+field) to get more items per page."
        ),
    }
    return {**result, KEY_META: {**meta, "truncated": truncated}, "data": kept_items}


def add_page_position(result: Any) -> Any:  # noqa: WPS210
    """
    Add returned, has_more and next_offset to the pagination of a page of items.

    The offset of the next page counts the items the page returns, so it also continues a page
    that fit_result_to_budget cut.

    Args:
        result: Marketplace API response, after fit_result_to_budget

    Returns:
        The response, with $meta.pagination.returned, and has_more and next_offset when the API
        gives the total; next_offset is None when no items follow or the page returned none
    """
    if not isinstance(result, dict):
        return result

    page_items = result.get("data")
    meta = result.get(KEY_META)
    pagination = meta.get("pagination") if isinstance(meta, dict) else None
    if not isinstance(page_items, list) or not isinstance(pagination, dict):
        return result

    page_position: dict[str, Any] = {"returned": len(page_items)}
    total = pagination.get("total")
    if total is not None:
        next_offset = (pagination.get("offset") or 0) + len(page_items)
        has_more = next_offset < total
        # A page without items, such as limit=0, does not move the offset: it has no next page
        has_next_page = has_more and bool(page_items)
        page_position |= {
            "has_more": has_more,
            "next_offset": next_offset if has_next_page else None,
        }

    return {**result, KEY_META: {**result[KEY_META], "pagination": {**pagination, **page_position}}}
