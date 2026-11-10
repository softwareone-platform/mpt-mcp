import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from mpt_mcp.tools.query.select_fields import sanitize_select, selects_audit
from mpt_mcp.tools.spec import MarketplaceSpec

logger = logging.getLogger(__name__)

# Table-friendly fields: full products are huge and break markdown tables (URLs, "|" in values)
CATALOG_PRODUCTS_SELECT = "-*,+id,+name,+shortDescription"
DEFAULT_LIMIT = 10
# The API rejects RQL with spaces after the commas (and(..., ilike(...) with 400
RQL_COMMA_SPACES = re.compile(r",\s+")


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
    query = with_audit.with_allowed_select(spec.get_item_fields(resource))
    return query, None if with_audit.select == fitted.select else fitted


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
