from typing import Any

KEPT_SCHEMA_KEYS = ("type", "description", "enum", "example")
MAX_SCHEMA_PROPERTIES = 10


class OpenAPIParser:
    """Parse OpenAPI specifications and extract GET endpoints."""

    def __init__(self, include_patterns: str = "", exclude_patterns: str = ""):
        """
        Initialize parser with optional filtering.

        Args:
            include_patterns: Comma-separated path patterns to include (empty = include all)
            exclude_patterns: Comma-separated path patterns to exclude
        """
        self.include_patterns = [
            pattern.strip() for pattern in include_patterns.split(",") if pattern.strip()
        ]
        self.exclude_patterns = [
            pattern.strip() for pattern in exclude_patterns.split(",") if pattern.strip()
        ]

    def extract_get_endpoints(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract all GET endpoints from an OpenAPI spec.

        Args:
            spec: OpenAPI specification dictionary

        Returns:
            One dict per GET endpoint with path, summary, description, parameters and response
        """
        endpoints = []
        for path, path_item in spec.get("paths", {}).items():
            if not self._should_include_path(path) or "get" not in path_item:
                continue

            get_op = path_item["get"]
            endpoints.append({
                "path": path,
                "summary": get_op.get("summary", f"GET {path}"),
                "description": get_op.get("description", ""),
                "parameters": get_op.get("parameters", []),
                "response": self._extract_response_info(get_op),
            })

        return endpoints

    def _extract_response_info(self, operation: dict[str, Any]) -> dict[str, Any]:
        """
        Extract response schema information from an operation.

        Args:
            operation: OpenAPI operation object

        Returns:
            Response information dictionary
        """
        responses = operation.get("responses", {})
        response_info = {}

        ok_response = responses.get("200")
        if ok_response is not None:
            response_info["description"] = ok_response.get("description", "")

            json_content = ok_response.get("content", {}).get("application/json")
            schema = json_content.get("schema") if json_content is not None else None
            if schema is not None:
                response_info["schema"] = self._simplify_schema(schema)

        return response_info

    def _should_include_path(self, path: str) -> bool:
        """
        Check if a path should be included based on filter patterns.

        Args:
            path: API path to check

        Returns:
            True if path should be included
        """
        normalized_path = path.strip("/")

        for pattern in self.exclude_patterns:
            if pattern in normalized_path:
                return False

        if self.include_patterns:
            return any(pattern in normalized_path for pattern in self.include_patterns)

        return True

    def _simplify_schema(
        self, schema: dict[str, Any], max_depth: int = 3, current_depth: int = 0
    ) -> dict[str, Any]:
        """
        Simplify a JSON schema for better readability in tool descriptions.

        Args:
            schema: The JSON schema to simplify
            max_depth: Maximum depth to traverse
            current_depth: Current traversal depth

        Returns:
            Simplified schema
        """
        if current_depth >= max_depth or not schema:
            return {"type": "object", "description": "..."}

        simplified = {key: schema[key] for key in KEPT_SCHEMA_KEYS if key in schema}

        properties = schema.get("properties")
        if isinstance(properties, dict):
            simplified["properties"] = {
                prop_name: self._simplify_schema(prop_schema, max_depth, current_depth + 1)
                for prop_name, prop_schema in list(properties.items())[:MAX_SCHEMA_PROPERTIES]
            }

        items_schema = schema.get("items")
        if items_schema is not None:
            simplified["items"] = self._simplify_schema(items_schema, max_depth, current_depth + 1)

        return simplified
