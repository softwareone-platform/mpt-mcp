from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from mpt_mcp.marketplace.schemas import OpenAPISpec

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Fallback when spec not available: include "failed" so audit.failed.at triggers auto-add
FALLBACK_STATIC_REGEX = re.compile(
    r"audit\.(created|updated|completed|processing|quoted|failed)\.(at|by)"
)
# An audit event says when (.at) or who (.by); the spec may name those fields differently
AUDIT_EVENT_FIELDS = frozenset(("actor", "at", "by", "date", "timestamp", "user"))


def build_audit_regex(events: set[str]) -> re.Pattern[str]:
    r"""Build regex audit\.(event1|event2|...).(at|by) from event names."""
    if not events:
        return FALLBACK_STATIC_REGEX

    part = "|".join(re.escape(error) for error in sorted(events))
    return re.compile(rf"audit\.({part})\.(at|by)")


def collect_audit_events(spec: OpenAPISpec, properties: dict[str, Any]) -> set[str]:
    """
    Find the audit properties of an item schema and collect the names of their events.

    The API always uses 'audit' as segment; the spec may use orderAudit etc.

    Args:
        spec: OpenAPI spec the schemas belong to, to resolve their references
        properties: Properties of the item schema

    Returns:
        Event names, such as created, updated or failed, that have a when or a who field
    """
    events: set[str] = set()
    for prop_name, prop_schema in properties.items():
        if "audit" in prop_name.lower():
            events.update(
                event_name
                for event_name, event_schema in get_schema_properties(spec, prop_schema).items()
                if AUDIT_EVENT_FIELDS & get_schema_properties(spec, event_schema).keys()
            )
    return events


def get_audit_data_from_spec(
    spec: OpenAPISpec,
    path_to_resource_id: Callable[[str], str],
) -> dict[str, Any]:
    """
    Walk OpenAPI spec and derive audit event names per resource.

    Audit is always on the **object** schema (the single-entity shape). We consider both:
    - **By-id paths** (e.g. /public/v1/commerce/orders/{id}): 200 response is the object
      schema (e.g. Order) with audit.
    - **Collection paths** (e.g. /public/v1/commerce/orders): 200 response is a list wrapper
      (e.g. { $meta, data: [items] }); we unwrap via get_item_schema to get the same object
      schema (Order) that has audit.

    So we always derive audit from the object schema; the collection returns those same objects.

    Returns { "events": set of str, "by_resource": { resource_id: [ "event1", "event2", ... ] } }.
    Paths are always audit.<event>.at and audit.<event>.by; we store only event names to keep
    payloads small.
    """
    by_resource = get_audit_events_by_resource(spec, path_to_resource_id)
    all_events = set().union(*by_resource.values())
    logger.info(
        "audit_fields: total resources with audit: %d, events: %s",
        len(by_resource),
        sorted(all_events),
    )
    return {
        "events": all_events,
        "by_resource": {resource: sorted(events) for resource, events in by_resource.items()},
    }


def get_audit_events_by_resource(
    spec: OpenAPISpec,
    path_to_resource_id: Callable[[str], str],
) -> dict[str, set[str]]:
    """
    Collect the audit events of every resource that has them.

    Args:
        spec: OpenAPI spec of a Marketplace endpoint
        path_to_resource_id: Function that names the resource of an API path

    Returns:
        Audit event names by resource; resources without events are left out
    """
    by_resource: dict[str, set[str]] = {}
    for path, path_item in spec.paths.items():
        events = get_path_audit_events(spec, path_item)
        if events:
            by_resource.setdefault(path_to_resource_id(path), set()).update(events)
    return by_resource


def get_path_audit_events(spec: OpenAPISpec, path_item: dict[str, Any]) -> set[str]:
    """
    Collect the audit events of the items a path returns.

    Args:
        spec: OpenAPI spec the path belongs to
        path_item: OpenAPI path item

    Returns:
        Audit event names of the items of the GET 200 response, empty when it has none
    """
    operation = path_item.get("get")
    if operation is None:
        return set()

    schema = spec.get_response_schema(operation)
    if not schema:
        return set()

    return collect_audit_events(spec, spec.get_item_schema(schema).get("properties") or {})


def get_schema_properties(spec: OpenAPISpec, schema: Any) -> dict[str, Any]:
    """
    Resolve a schema and return its properties.

    Args:
        spec: OpenAPI spec the schema belongs to, to resolve its references
        schema: Schema, or any other value found where a schema was expected

    Returns:
        Properties of the resolved schema, empty when it is not an object schema
    """
    if not isinstance(schema, dict):
        return {}

    resolved_schema = spec.resolve_schema(schema)
    if not isinstance(resolved_schema, dict):
        return {}

    properties: dict[str, Any] = resolved_schema.get("properties") or {}
    return properties
