import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from mpt_mcp.tools.dependencies import MarketplaceSpec
from mpt_mcp.tools.resources import get_response_item_schema

logger = logging.getLogger(__name__)

# Table-friendly fields: full products are huge and break markdown tables (URLs, "|" in values)
CATALOG_PRODUCTS_SELECT = "-*,+id,+name,+shortDescription"
DEFAULT_LIMIT = 10
# The API rejects RQL with spaces after the commas (and(..., ilike(...) with 400
RQL_COMMA_SPACES = re.compile(r",\s+")
# When present in schema, these fields are always added to select so responses are usable (id,
# status, name).
_ALWAYS_INCLUDE_WHEN_IN_SCHEMA = ("id", "status", "name")


@dataclass(frozen=True)
class QueryParams:
    """Query parameters of one Marketplace API request."""

    limit: int | None
    offset: int | None
    order: str | None
    rql: str
    select: str | None

    def to_query(self) -> dict[str, Any]:
        """Return the parameters to send to the API, without the empty ones."""
        query_params = {
            "rql": self.rql,
            "limit": self.limit,
            "offset": self.offset,
            "select": self.select,
            "order": self.order,
        }
        return {
            name: param_value
            for name, param_value in query_params.items()
            if param_value not in {None, ""}
        }

    def with_allowed_select(self, allowed_fields: set[str]) -> QueryParams:
        """Keep in select only the fields of the resource, plus id, status and name."""
        if not self.select:
            return self

        return replace(self, select=sanitize_select(self.select, allowed_fields) or self.select)

    def with_default_select(self, resource: str) -> QueryParams:
        """Use the table-friendly select of catalog.products when no select is given."""
        if resource != "catalog.products" or (self.select or "").strip():
            return self

        logger.info(
            "Default select for catalog.products: %s (omit select for full fields)",
            CATALOG_PRODUCTS_SELECT,
        )
        return replace(self, select=CATALOG_PRODUCTS_SELECT)

    def with_page_for(self, resource: str, endpoint_path: str) -> QueryParams:
        """Drop limit and offset for a path that ends in a parameter: it returns a single item."""
        if not endpoint_path.endswith("}"):
            return self

        if self.offset is not None or self.limit != DEFAULT_LIMIT:
            logger.info("Ignored limit and offset: %s returns a single item", resource)
        return replace(self, limit=None, offset=None)

    def with_used_audit_fields(self, audit_pattern: re.Pattern[str]) -> QueryParams:
        """
        Select the audit fields rql or order use, so the result shows their values.

        Only the fields in use: the whole audit object doubles the size of small items.
        """
        audit_paths = get_used_audit_paths(self.rql, self.order, audit_pattern)
        if not audit_paths or selects_audit(self.select):
            return self

        audit_select = ",".join(f"+{audit_path}" for audit_path in audit_paths)
        logger.info("Auto-added %s to select (audit fields used to filter or sort)", audit_select)
        select = f"{self.select},{audit_select}" if self.select else audit_select
        return replace(self, select=select)


def build_query(
    resource: str, endpoint_path: str, requested: QueryParams, spec: MarketplaceSpec
) -> tuple[QueryParams, QueryParams | None]:
    """
    Build the query to send from the tool arguments.

    Args:
        resource: Resource name
        endpoint_path: API path template of the resource
        requested: Query parameters as the caller gave them
        spec: OpenAPI spec of the endpoint, for the audit and select fields

    Returns:
        Query to send, and the same query without the audit fields it added, to retry with when
        the API rejects them (None when it added none)
    """
    fitted = replace(
        requested.with_default_select(resource).with_page_for(resource, endpoint_path),
        rql=RQL_COMMA_SPACES.sub(",", requested.rql),
    )
    with_audit = fitted.with_used_audit_fields(spec.audit_regex)
    allowed_fields = get_allowed_select_fields(spec.openapi_spec, spec.endpoints_registry, resource)
    query = with_audit.with_allowed_select(allowed_fields)
    return query, None if with_audit.select == fitted.select else fitted


def get_allowed_select_fields(
    openapi_spec: dict[str, Any],
    endpoints_registry: dict[str, Any],
    resource: str,
) -> set[str]:
    """Return the top-level fields allowed in select, from the GET response item schema."""
    item_schema = get_response_item_schema(openapi_spec, endpoints_registry, resource)
    return set((item_schema.get("properties") or {}).keys())


def get_used_audit_paths(rql: str, order: str | None, audit_pattern: re.Pattern[str]) -> list[str]:
    """
    List the audit fields a query filters or sorts by, in the order they first appear.

    Args:
        rql: RQL query string
        order: Sort order, such as -audit.created.at
        audit_pattern: Audit fields of the resource, such as audit.created.at

    Returns:
        Audit fields such as audit.created.at, or audit when order sorts by the whole object
    """
    audit_paths = [match.group(0) for match in audit_pattern.finditer(rql or "")]
    for order_part in (order or "").split(","):
        order_field = order_part.strip().lstrip("+-")
        if order_field.lower().startswith("audit"):
            audit_paths.append(order_field)
    return list(dict.fromkeys(audit_paths))


def sanitize_select(
    select: str | None,
    allowed_fields: set[str],
) -> str | None:
    """
    Keep only the allowed top-level fields in select and always include id.

    Status and name are added too when the schema has them.

    Drops any part whose top-level field is not in allowed_fields (if allowed_fields is non-empty).
    """
    if not select or not select.strip():
        return select

    parts = [select_part.strip() for select_part in select.split(",") if select_part.strip()]
    if not parts:
        return select

    has_exclude_all = parts[0] == "-*"
    if has_exclude_all:
        parts = parts[1:]

    kept: list[str] = []
    dropped: list[str] = []
    for part in parts:
        if allowed_fields and top_level_field(part) not in allowed_fields:
            dropped.append(part)
            continue
        kept.append(part)
    if dropped:
        logger.info("Select sanitized: dropped fields not in schema: %s", ", ".join(dropped))

    tops = {top_level_field(select_part) for select_part in kept}
    to_add: list[str] = []
    for field in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA:
        if field in tops:
            continue
        if field == "id" or (allowed_fields and field in allowed_fields):
            to_add.append(field)
            tops.add(field)
    if to_add:
        logger.info("Select: added %s (always included when in schema)", ", ".join(to_add))
    prefix = [
        always_field for always_field in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA if always_field in tops
    ]
    rest = [
        select_part
        for select_part in kept
        if top_level_field(select_part) not in _ALWAYS_INCLUDE_WHEN_IN_SCHEMA
    ]
    kept = prefix + rest

    # Re-add -* at the start if it was present (and convert bare fields to +field when -* is used)
    if has_exclude_all:
        kept = [
            select_part if select_part.startswith(("+", "-")) else f"+{select_part}"
            for select_part in kept
        ]
        selected = ",".join(kept)
        return f"-*,{selected}" if kept else "-*"

    return ",".join(kept)


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
