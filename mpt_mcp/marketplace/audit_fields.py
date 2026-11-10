from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from mpt_mcp.marketplace.schemas import OpenAPISpec

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

type AuditPaths = list[dict[str, str]]

# Fallback when spec not available: include "failed" so audit.failed.at triggers auto-add
FALLBACK_STATIC_REGEX = re.compile(
    r"audit\.(created|updated|completed|processing|quoted|failed)\.(at|by)"
)


def collect_audit_events_and_paths_from_props(
    spec: OpenAPISpec,
    properties: dict[str, Any],
) -> tuple[set[str], AuditPaths]:
    """
    Find the audit property in a flat 'properties' dict and collect its events and paths.

    Events are names like created, updated or failed; paths are audit.<event>.at and .by.
    The API always uses 'audit' as segment; the spec may use orderAudit etc.
    """
    events: set[str] = set()
    paths: AuditPaths = []
    for prop_name, prop_schema in (properties or {}).items():
        if "audit" not in prop_name.lower():
            continue
        audit_schema = (
            spec.resolve_schema(prop_schema) if isinstance(prop_schema, dict) else prop_schema
        )
        if not isinstance(audit_schema, dict):
            continue
        nested = audit_schema.get("properties") or {}
        for event_name, event_schema in nested.items():
            if not isinstance(event_schema, dict):
                continue
            resolved_schema = spec.resolve_schema(event_schema)
            event_props = (
                (resolved_schema.get("properties") or {})
                if isinstance(resolved_schema, dict)
                else {}
            )
            # .at = when (spec may use "at", "timestamp", or "date"), .by = who (spec may use "by",
            # "actor", or "user")
            has_when = "at" in event_props or "timestamp" in event_props or "date" in event_props
            has_who = "by" in event_props or "actor" in event_props or "user" in event_props
            if has_when:
                events.add(event_name)
                paths.append({"path": f"audit.{event_name}.at", "event": event_name, "type": "at"})
            if has_who:
                events.add(event_name)
                paths.append({"path": f"audit.{event_name}.by", "event": event_name, "type": "by"})
    return events, paths


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
    all_events: set[str] = set()
    by_resource: dict[str, list[str]] = {}
    paths = spec.document.get("paths") or {}
    get_paths = [path for path, path_item in paths.items() if "get" in path_item]
    logger.debug("audit_fields: scanning %d GET paths for audit schemas", len(get_paths))
    for path, path_item in paths.items():
        if "get" not in path_item:
            continue
        schema = spec.get_response_schema(path_item["get"])
        if not schema:
            continue
        schema = spec.get_item_schema(schema)
        properties = schema.get("properties")
        if not properties:
            continue
        if not any("audit" in name.lower() for name in properties):
            continue
        events, _ = collect_audit_events_and_paths_from_props(spec, properties)
        if not events:
            continue
        all_events |= events
        resource_id = path_to_resource_id(path)
        existing_events = set(by_resource.get(resource_id) or [])
        existing_events |= events
        by_resource[resource_id] = sorted(existing_events)
    logger.info(
        "audit_fields: total resources with audit: %d, events: %s",
        len(by_resource),
        sorted(all_events),
    )
    return {"events": all_events, "by_resource": by_resource}


def build_audit_regex(events: set[str]) -> re.Pattern[str]:
    r"""Build regex audit\.(event1|event2|...).(at|by) from event names."""
    if not events:
        return FALLBACK_STATIC_REGEX

    part = "|".join(re.escape(error) for error in sorted(events))
    return re.compile(rf"audit\.({part})\.(at|by)")
