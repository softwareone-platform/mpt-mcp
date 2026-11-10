from dataclasses import dataclass
from typing import Any

MEDIA_TYPE_JSON = "application/json"


@dataclass(frozen=True)
class OpenAPISpec:  # noqa: WPS214
    """OpenAPI document of a Marketplace endpoint, with the lookups of its paths and schemas."""

    document: dict[str, Any]

    @property
    def api_info(self) -> dict[str, Any]:
        """Return the info object of the spec: its title, version and description."""
        return self.document.get("info") or {}

    @property
    def paths(self) -> dict[str, Any]:
        """Return the path items of the spec, by API path."""
        return self.document.get("paths") or {}

    @property
    def version(self) -> str:
        """Return the OpenAPI version of the spec, 3.0 when it does not say."""
        return self.document.get("openapi") or "3.0"

    def get_item_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """
        Get the item schema for list-like responses.

        Handles: (1) array with items, (2) $ref to array/list schema,
        (3) object with a 'data' property that is an array (marketplace API list responses).
        """
        list_items = self._get_list_items(schema)
        if list_items is not None:
            return list_items

        ref = schema.get("$ref")
        if ref is not None:
            return self.get_item_schema(self.resolve_ref(ref))

        # List endpoints often return { "$meta", "data": [ items ] }; use item schema for audit
        # Some specs omit "type": "object", so check for "properties" with "data" as well
        if schema.get("type") != "object" and "properties" not in schema:
            return schema

        properties = schema.get("properties") or {}
        for key in ("data", "items", "results"):
            list_items = self._get_list_items(properties.get(key))
            if list_items is not None:
                return list_items

        return schema

    def get_operation(self, path: str, method: str = "get") -> dict[str, Any] | None:
        """
        Return an operation of an API path.

        Args:
            path: API path, with its path parameters in braces
            method: HTTP method of the operation, in lowercase

        Returns:
            The operation, or None when the spec does not have it
        """
        path_item = self.paths.get(path)
        operation = path_item.get(method) if isinstance(path_item, dict) else None
        return operation if isinstance(operation, dict) else None

    def get_response_item_schema(self, path: str) -> dict[str, Any]:
        """
        Return the schema of one item of the GET response of an API path.

        List responses wrap their items as {"$meta": ..., "data": [items]}; the item schema is the
        one inside data, and single-item responses are the item themselves.

        Args:
            path: API path, with its path parameters in braces

        Returns:
            Item schema with its $ref and allOf resolved, or {} when the spec does not describe it
        """
        operation = self.get_operation(path)
        if operation is None:
            return {}

        schema = self.get_response_schema(operation)
        if not schema:
            return {}

        resolved = self.resolve_schema(self.get_item_schema(schema))
        return resolved if isinstance(resolved, dict) else {}

    def get_response_schema(self, operation: dict[str, Any]) -> dict[str, Any] | None:
        """
        Return the schema of the 200 JSON response of an operation, with its top $ref resolved.

        Args:
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
        return schema if ref is None else self.resolve_ref(ref)

    def resolve_ref(self, ref: str) -> dict[str, Any]:
        """Resolve $ref (e.g. #/components/schemas/Order) to the schema object."""
        if not ref or not ref.startswith("#/"):
            return {}

        parts = ref.replace("#/", "").split("/")
        out: Any = self.document
        for part in parts:
            out = out.get(part, {}) if isinstance(out, dict) else {}
        return out if isinstance(out, dict) else {}

    def resolve_schema(self, schema: Any) -> Any:
        """
        Resolve schema that may use $ref or allOf (common in downloaded OpenAPI specs).

        Returns the schema that actually has 'properties' so we can detect audit events.
        """
        if not isinstance(schema, dict):
            return schema

        ref = schema.get("$ref")
        if ref is not None:
            return self.resolve_schema(self.resolve_ref(ref))

        for part in schema.get("allOf", ()):
            part_ref = part.get("$ref") if isinstance(part, dict) else None
            if part_ref is not None:
                resolved = self.resolve_schema(self.resolve_ref(part_ref))
                if resolved:
                    return resolved

        return schema

    def _get_list_items(self, list_schema: Any) -> dict[str, Any] | None:
        list_ref = list_schema.get("$ref") if isinstance(list_schema, dict) else None
        if list_ref is not None:
            list_schema = self.resolve_ref(list_ref)
        is_array = isinstance(list_schema, dict) and list_schema.get("type") == "array"
        if not is_array or "items" not in list_schema:
            return None

        item_schema = list_schema["items"]
        if isinstance(item_schema, dict) and "$ref" in item_schema:
            return self.resolve_ref(item_schema["$ref"])

        return item_schema if isinstance(item_schema, dict) else {}
