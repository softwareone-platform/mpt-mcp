import logging

logger = logging.getLogger(__name__)

# Added to select when the schema has them, so every item shows what it is
ALWAYS_SELECTED_FIELDS = ("id", "status", "name")


def add_always_selected(select_parts: list[str], allowed_fields: set[str]) -> list[str]:
    """
    Put id, and status and name when the schema has them, first in select.

    Args:
        select_parts: Select entries, e.g. ["+audit", "status"]
        allowed_fields: Top-level fields of the resource items, empty when unknown

    Returns:
        The always selected fields, then the other entries in their order
    """
    selected = {top_level_field(select_part) for select_part in select_parts}
    always_selected = [
        field
        for field in ALWAYS_SELECTED_FIELDS
        if field in selected or field == "id" or field in allowed_fields
    ]
    added = [field for field in always_selected if field not in selected]
    if added:
        logger.info("Select: added %s (always included when in schema)", ", ".join(added))
    return always_selected + [
        select_part
        for select_part in select_parts
        if top_level_field(select_part) not in ALWAYS_SELECTED_FIELDS
    ]


def keep_allowed_fields(select_parts: list[str], allowed_fields: set[str]) -> list[str]:
    """
    Drop the select entries whose top-level field the resource items do not have.

    Args:
        select_parts: Select entries, e.g. ["+audit", "orderNumber"]
        allowed_fields: Top-level fields of the resource items, empty when unknown

    Returns:
        The entries of allowed fields, or all of them when allowed_fields is empty
    """
    if not allowed_fields:
        return select_parts

    dropped = [part for part in select_parts if top_level_field(part) not in allowed_fields]
    if dropped:
        logger.info("Select sanitized: dropped fields not in schema: %s", ", ".join(dropped))
    return [part for part in select_parts if top_level_field(part) in allowed_fields]


def sanitize_select(select: str | None, allowed_fields: set[str]) -> str | None:
    """
    Keep only the allowed top-level fields in select and always include id.

    Status and name are added too when the schema has them.

    Args:
        select: Select string, e.g. -*,+audit,+orderNumber
        allowed_fields: Top-level fields of the resource items, empty when unknown

    Returns:
        Select with the always selected fields first, or select as it is when it has no entries
    """
    stripped_parts = (part.strip() for part in (select or "").split(","))
    select_parts = [part for part in stripped_parts if part]
    if not select_parts:
        return select

    exclude_all = select_parts[0] == "-*"
    sanitized = add_always_selected(
        keep_allowed_fields(select_parts[1:] if exclude_all else select_parts, allowed_fields),
        allowed_fields,
    )
    if not exclude_all:
        return ",".join(sanitized)

    # After -* every field needs its + prefix
    prefixed = [part if part[0] in "+-" else f"+{part}" for part in sanitized]
    return ",".join(["-*", *prefixed])


def selects_audit(select: str | None) -> bool:
    """
    Tell whether select already asks for the audit object or one of its fields.

    Args:
        select: Select string, e.g. +id,+audit.created.at

    Returns:
        True when an entry is audit, +audit or an audit.* field
    """
    select_parts = [select_part.strip() for select_part in (select or "").split(",")]
    return any(
        part in {"audit", "+audit"} or part.startswith(("audit.", "+audit."))
        for part in select_parts
    )


def top_level_field(select_part: str) -> str:
    """
    Return the top-level field a select entry refers to.

    Args:
        select_part: One select entry, e.g. +product.name or -audit

    Returns:
        Field name without its +/- prefix and nested path, e.g. product
    """
    return select_part.lstrip("+-").split(".")[0]
