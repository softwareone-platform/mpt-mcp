from typing import Any


class OpenAPIParser:
    """Parse OpenAPI specifications and extract GET endpoints."""

    def __init__(self, include_patterns: str = "", exclude_patterns: str = ""):
        """
        Initialize parser with optional filtering.

        Args:
            include_patterns: Comma-separated path patterns to include (empty = include all)
            exclude_patterns: Comma-separated path patterns to exclude
        """
        self.include_patterns = [p.strip() for p in include_patterns.split(",") if p.strip()]
        self.exclude_patterns = [p.strip() for p in exclude_patterns.split(",") if p.strip()]

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

        simplified = {}

        if "type" in schema:
            simplified["type"] = schema["type"]

        if "description" in schema:
            simplified["description"] = schema["description"]

        if "enum" in schema:
            simplified["enum"] = schema["enum"]

        if "properties" in schema and isinstance(schema["properties"], dict):
            simplified["properties"] = {}
            for prop_name, prop_schema in list(schema["properties"].items())[
                :10
            ]:  # Limit to 10 properties
                simplified["properties"][prop_name] = self._simplify_schema(
                    prop_schema, max_depth, current_depth + 1
                )

        if "items" in schema:
            simplified["items"] = self._simplify_schema(
                schema["items"], max_depth, current_depth + 1
            )

        if "example" in schema:
            simplified["example"] = schema["example"]

        return simplified

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

        if "200" in responses:
            response_200 = responses["200"]
            response_info["description"] = response_200.get("description", "")

            content = response_200.get("content", {})
            if "application/json" in content:
                json_content = content["application/json"]
                if "schema" in json_content:
                    response_info["schema"] = self._simplify_schema(json_content["schema"])

        return response_info
