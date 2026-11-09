from typing import Any

MEDIA_TYPE_JSON = "application/json"


def get_response_item_schema(
    openapi_spec: dict[str, Any],
    endpoints_registry: dict[str, Any],
    resource: str,
) -> dict[str, Any]:
    """
    Return the schema of one item of a resource's GET response.

    List responses wrap their items as {"$meta": ..., "data": [items]}; the item schema is the
    one inside data, and single-item responses are the item themselves.

    Args:
        openapi_spec: The full OpenAPI specification
        endpoints_registry: Registry of available endpoints
        resource: The resource to get the item schema for

    Returns:
        Item schema with its $ref and allOf resolved, or {} when the spec does not describe it
    """
    path = (endpoints_registry.get(resource) or {}).get("path")
    operation = get_get_operation(openapi_spec, path) if path else None
    if operation is None:
        return {}

    schema = get_response_schema(openapi_spec, operation)
    if not schema:
        return {}

    resolved = resolve_schema(openapi_spec, get_item_schema(openapi_spec, schema))
    return resolved if isinstance(resolved, dict) else {}


def get_get_operation(
    openapi_spec: dict[str, Any],
    path: str,
) -> dict[str, Any] | None:
    """
    Return the GET operation of an API path.

    Args:
        openapi_spec: The full OpenAPI specification
        path: API path, with its path parameters in braces

    Returns:
        GET operation of the path, or None when the spec does not have it
    """
    path_item = (openapi_spec.get("paths") or {}).get(path)
    operation = path_item.get("get") if isinstance(path_item, dict) else None
    return operation if isinstance(operation, dict) else None


def get_response_schema(
    openapi_spec: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Return the schema of the 200 JSON response of an operation, with its top $ref resolved.

    Args:
        openapi_spec: The full OpenAPI specification
        operation: Operation of a path, such as its GET operation

    Returns:
        Response schema, or None when the operation has no 200 JSON response schema
    """
    ok_response = (operation.get("responses") or {}).get("200") or {}
    json_content = (ok_response.get("content") or {}).get(MEDIA_TYPE_JSON) or {}
    schema = json_content.get("schema")
    if not isinstance(schema, dict):
        return None

    ref = schema.get("$ref")
    return schema if ref is None else resolve_ref(openapi_spec, ref)


def get_item_schema(
    spec: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Get the item schema for list-like responses.

    Handles: (1) array with items, (2) $ref to array/list schema,
    (3) object with a 'data' property that is an array (marketplace API list responses).
    """
    if schema.get("type") == "array" and "items" in schema:
        item_schema = schema["items"]
        if isinstance(item_schema, dict) and "$ref" in item_schema:
            return resolve_ref(spec, item_schema["$ref"])

        return item_schema if isinstance(item_schema, dict) else {}

    ref = schema.get("$ref")
    if ref is not None:
        return get_item_schema(spec, resolve_ref(spec, ref))

    # List endpoints often return { "$meta", "data": [ items ] }; use item schema for audit
    # Some specs omit "type": "object", so check for "properties" with "data" as well
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        for key in ("data", "items", "results"):
            prop = properties.get(key)
            if prop is not None:
                prop_ref = prop.get("$ref") if isinstance(prop, dict) else None
                if prop_ref is not None:
                    prop = resolve_ref(spec, prop_ref)
                is_array = isinstance(prop, dict) and prop.get("type") == "array"
                if is_array and "items" in prop:
                    item_schema = prop["items"]
                    if isinstance(item_schema, dict) and "$ref" in item_schema:
                        return resolve_ref(spec, item_schema["$ref"])

                    return item_schema if isinstance(item_schema, dict) else {}

    return schema


def resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve $ref (e.g. #/components/schemas/Order) to the schema object."""
    if not ref or not ref.startswith("#/"):
        return {}

    parts = ref.replace("#/", "").split("/")
    out: Any = spec
    for part in parts:
        out = out.get(part, {}) if isinstance(out, dict) else {}
    return out if isinstance(out, dict) else {}


def resolve_schema(
    spec: dict[str, Any],
    schema: Any,
) -> Any:
    """
    Resolve schema that may use $ref or allOf (common in downloaded OpenAPI specs).

    Returns the schema that actually has 'properties' so we can detect audit events.
    """
    if not isinstance(schema, dict):
        return schema

    ref = schema.get("$ref")
    if ref is not None:
        return resolve_schema(spec, resolve_ref(spec, ref))

    for part in schema.get("allOf", ()):
        part_ref = part.get("$ref") if isinstance(part, dict) else None
        if part_ref is not None:
            resolved = resolve_schema(spec, resolve_ref(spec, part_ref))
            if resolved:
                return resolved

    return schema
