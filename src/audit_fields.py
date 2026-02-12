import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# In-memory cache: key (api_base_url or spec URL) -> { "events", "regex", "by_resource" }
_audit_cache: dict[str, dict[str, Any]] = {}

# Fallback when spec not available: include "failed" so audit.failed.at triggers auto-add
FALLBACK_STATIC_REGEX = re.compile(r"audit\.(created|updated|completed|processing|quoted|failed)\.(at|by)")


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve $ref (e.g. #/components/schemas/Order) to the schema object."""
    if not ref or not ref.startswith("#/"):
        return {}
    parts = ref.replace("#/", "").split("/")
    out = spec
    for p in parts:
        out = out.get(p, {}) if isinstance(out, dict) else {}
    return out if isinstance(out, dict) else {}


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve schema that may use $ref or allOf (common in downloaded OpenAPI specs).
    Returns the schema that actually has 'properties' so we can detect audit events.
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return _resolve_schema(spec, _resolve_ref(spec, schema["$ref"]))
    if "allOf" in schema:
        for part in schema["allOf"]:
            if isinstance(part, dict) and "$ref" in part:
                resolved = _resolve_schema(spec, _resolve_ref(spec, part["$ref"]))
                if resolved:
                    return resolved
    return schema


def _get_item_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """
    Get the item schema for list-like responses.
    Handles: (1) array with items, (2) $ref to array/list schema,
    (3) object with a 'data' property that is an array (marketplace API list responses).
    """
    if schema.get("type") == "array" and "items" in schema:
        items = schema["items"]
        if isinstance(items, dict) and "$ref" in items:
            return _resolve_ref(spec, items["$ref"])
        return items if isinstance(items, dict) else {}
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        return _get_item_schema(spec, resolved)
    # List endpoints often return { "$meta", "data": [ items ] }; use item schema for audit
    # Some specs omit "type": "object", so check for "properties" with "data" as well
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        for key in ("data", "items", "results"):
            if key in properties:
                prop = properties[key]
                if isinstance(prop, dict) and "$ref" in prop:
                    prop = _resolve_ref(spec, prop["$ref"])
                if isinstance(prop, dict) and prop.get("type") == "array" and "items" in prop:
                    items = prop["items"]
                    if isinstance(items, dict) and "$ref" in items:
                        return _resolve_ref(spec, items["$ref"])
                    return items if isinstance(items, dict) else {}
    return schema


def _collect_audit_events_and_paths_from_props(
    spec: dict[str, Any],
    properties: dict[str, Any],
) -> tuple[set[str], list[dict[str, str]]]:
    """
    From a flat 'properties' dict, find the property whose name contains 'audit'
    and collect event names (created, updated, failed, ...) and paths (audit.<event>.at, .by).
    API always uses 'audit' as segment; spec may use orderAudit etc.
    """
    events: set[str] = set()
    paths: list[dict[str, str]] = []
    for prop_name, prop_schema in (properties or {}).items():
        if "audit" not in prop_name.lower():
            continue
        obj = _resolve_schema(spec, prop_schema) if isinstance(prop_schema, dict) else prop_schema
        if not isinstance(obj, dict):
            continue
        nested = obj.get("properties") or {}
        for event_name, event_schema in nested.items():
            if not isinstance(event_schema, dict):
                continue
            event_schema = _resolve_schema(spec, event_schema)
            event_props = (event_schema.get("properties") or {}) if isinstance(event_schema, dict) else {}
            # .at = when (spec may use "at", "timestamp", or "date"), .by = who (spec may use "by", "actor", or "user")
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
    spec: dict[str, Any],
    path_to_resource_id: Callable[[str], str],
) -> dict[str, Any]:
    """
    Walk OpenAPI spec and derive audit event names per resource.

    Audit is always on the **object** schema (the single-entity shape). We consider both:
    - **By-id paths** (e.g. /public/v1/commerce/orders/{id}): 200 response is the object schema (e.g. Order) with audit.
    - **Collection paths** (e.g. /public/v1/commerce/orders): 200 response is a list wrapper (e.g. { $meta, data: [items] });
      we unwrap via _get_item_schema to get the same object schema (Order) that has audit.

    So we always derive audit from the object schema; the collection returns those same objects.

    Returns { "events": set of str, "by_resource": { resource_id: [ "event1", "event2", ... ] } }.
    Paths are always audit.<event>.at and audit.<event>.by; we store only event names to keep payloads small.
    """
    all_events: set[str] = set()
    by_resource: dict[str, list[str]] = {}
    paths = spec.get("paths") or {}
    get_paths = [p for p, pi in paths.items() if "get" in pi]
    logger.debug("audit_fields: scanning %d GET paths for audit schemas", len(get_paths))
    for path, path_item in paths.items():
        if "get" not in path_item:
            continue
        get_op = path_item["get"]
        responses = get_op.get("responses") or {}
        content = (responses.get("200") or {}).get("content") or {}
        json_content = content.get("application/json") or {}
        schema = json_content.get("schema")
        if not schema:
            logger.debug("audit_fields: %s has no 200 application/json schema", path)
            continue
        if "$ref" in schema:
            schema = _resolve_ref(spec, schema["$ref"])
        schema = _get_item_schema(spec, schema)
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        if not properties:
            logger.debug("audit_fields: %s item schema has no properties", path)
            continue
        prop_names = list(properties.keys())
        audit_like = [n for n in prop_names if "audit" in n.lower()]
        if not audit_like:
            logger.debug("audit_fields: %s properties (no *audit*): %s", path, prop_names[:12])
            continue
        logger.debug("audit_fields: %s has audit-like props: %s", path, audit_like)
        events, _ = _collect_audit_events_and_paths_from_props(spec, properties)
        if not events:
            logger.debug("audit_fields: %s audit-like %s resolved to 0 events (check nested .at/.by)", path, audit_like)
            continue
        all_events |= events
        resource_id = path_to_resource_id(path)
        existing_events = set(by_resource.get(resource_id) or [])
        existing_events |= events
        by_resource[resource_id] = sorted(existing_events)
        logger.debug("audit_fields: %s -> %s: events %s", path, resource_id, by_resource[resource_id])
    logger.info("audit_fields: total resources with audit: %d, events: %s", len(by_resource), sorted(all_events))
    return {"events": all_events, "by_resource": by_resource}


def build_audit_regex(events: set[str]) -> re.Pattern[str]:
    r"""Build regex audit\.(event1|event2|...).(at|by) from event names."""
    if not events:
        return FALLBACK_STATIC_REGEX
    part = "|".join(re.escape(e) for e in sorted(events))
    return re.compile(rf"audit\.({part})\.(at|by)")


def update_cache(cache_key: str, spec: dict[str, Any], path_to_resource_id: Callable[[str], str]) -> None:
    """
    Compute audit data from spec and store in cache under cache_key.
    Call this when the spec is loaded (endpoint_registry or server_stdio init).
    """
    import os

    if os.getenv("DEBUG", "").lower() == "true":
        logger.setLevel(logging.DEBUG)
    data = get_audit_data_from_spec(spec, path_to_resource_id)
    _audit_cache[cache_key] = {
        "events": data["events"],
        "regex": build_audit_regex(data["events"]),
        "by_resource": data["by_resource"],
    }


def get_audit_regex(cache_key: str | None) -> re.Pattern[str]:
    """
    Return cached regex for the given cache key (api_base_url or spec URL).
    If not in cache, return fallback static regex (includes failed).
    """
    if cache_key and cache_key in _audit_cache:
        return _audit_cache[cache_key]["regex"]
    return FALLBACK_STATIC_REGEX


def get_audit_fields(cache_key: str | None, resource: str | None = None) -> dict[str, Any]:
    """
    Return cached audit event names for the given cache key.
    Paths are always audit.<event>.at and audit.<event>.by.
    If resource is provided, return { "resource": resource, "events": [...] } or error.
    If resource is None, return { "by_resource": { resource_id: ["event1", "event2", ...], ... } } for all resources.
    """
    if not cache_key or cache_key not in _audit_cache:
        if resource:
            return {"error": "Audit fields not available (spec not loaded)", "resource": resource or ""}
        return {"by_resource": {}}
    by_resource = _audit_cache[cache_key]["by_resource"]
    if resource is not None:
        if resource not in by_resource:
            return {"resource": resource, "events": [], "hint": "No audit fields found for this resource"}
        return {"resource": resource, "events": by_resource[resource]}
    return {"by_resource": by_resource}
