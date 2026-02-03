"""
OpenAPI specification parser for extracting GET endpoints
"""

import json
from typing import Any

from mcp.types import Tool


class OpenAPIParser:
    """Parse OpenAPI specifications and extract GET endpoints"""

    def __init__(self, include_patterns: str = "", exclude_patterns: str = ""):
        """
        Initialize parser with optional filtering

        Args:
            include_patterns: Comma-separated path patterns to include (empty = include all)
            exclude_patterns: Comma-separated path patterns to exclude
        """
        self.include_patterns = [p.strip() for p in include_patterns.split(",") if p.strip()]
        self.exclude_patterns = [p.strip() for p in exclude_patterns.split(",") if p.strip()]

    def _should_include_path(self, path: str) -> bool:
        """
        Check if a path should be included based on filter patterns

        Args:
            path: API path to check

        Returns:
            True if path should be included
        """
        # Normalize path (remove leading/trailing slashes)
        normalized_path = path.strip("/")

        # If exclude patterns specified, check if path matches any
        for pattern in self.exclude_patterns:
            if pattern in normalized_path:
                return False

        # If include patterns specified, path must match at least one
        if self.include_patterns:
            return any(pattern in normalized_path for pattern in self.include_patterns)

        # No filters or passed all checks
        return True

    def _sanitize_tool_name(self, name: str) -> str:
        """
        Sanitize tool name to match MCP requirements: ^[a-zA-Z0-9_-]{1,64}$

        Args:
            name: Original tool name

        Returns:
            Sanitized tool name
        """
        import re

        # Replace invalid characters with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        # Remove leading/trailing underscores
        sanitized = sanitized.strip("_")
        # Limit to 64 characters
        sanitized = sanitized[:64]
        # Ensure it's not empty
        if not sanitized:
            sanitized = "tool"
        return sanitized

    async def extract_get_endpoints(self, spec: dict[str, Any]) -> list[Tool]:
        """
        Extract all GET endpoints from OpenAPI spec and convert to MCP tools

        Args:
            spec: OpenAPI specification dictionary

        Returns:
            List of MCP Tool objects for GET endpoints
        """
        tools = []
        paths = spec.get("paths", {})

        for path, path_item in paths.items():
            # Check if path should be included based on filters
            if not self._should_include_path(path):
                continue

            # Check if GET operation exists
            if "get" not in path_item:
                continue

            get_op = path_item["get"]

            # Extract operation info
            operation_id = get_op.get("operationId", path.replace("/", "_").strip("_"))
            # Sanitize the operation_id to match MCP requirements
            operation_id = self._sanitize_tool_name(operation_id)
            summary = get_op.get("summary", f"GET {path}")
            description = get_op.get("description", "")

            # Extract parameters (query, header, path)
            parameters = get_op.get("parameters", [])
            input_schema = self._build_input_schema(path, parameters)

            # Add common query parameters (RQL, pagination, etc.) if not already present
            self._add_common_query_params(input_schema)

            # Extract response information
            response_info = self._extract_response_info(get_op)

            # Build tool description with response info
            tool_description = {
                "method": "GET",
                "path": path,
                "summary": summary,
                "description": description,
                "parameters": parameters,
                "response": response_info,
            }

            # Create MCP Tool with flexible schema
            # Note: additionalProperties allows passing any query params, including RQL expressions
            tool = Tool(
                name=operation_id,
                description=json.dumps(tool_description),
                inputSchema={
                    "type": "object",
                    "properties": input_schema.get("properties", {}),
                    "required": input_schema.get("required", []),
                    "additionalProperties": True,  # Allow RQL and other undocumented query params
                },
            )

            tools.append(tool)

        return tools

    def _simplify_schema(self, schema: dict[str, Any], max_depth: int = 3, current_depth: int = 0) -> dict[str, Any]:
        """
        Simplify a JSON schema for better readability in tool descriptions

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
            for prop_name, prop_schema in list(schema["properties"].items())[:10]:  # Limit to 10 properties
                simplified["properties"][prop_name] = self._simplify_schema(prop_schema, max_depth, current_depth + 1)

        if "items" in schema:
            simplified["items"] = self._simplify_schema(schema["items"], max_depth, current_depth + 1)

        if "example" in schema:
            simplified["example"] = schema["example"]

        return simplified

    def _extract_response_info(self, operation: dict[str, Any]) -> dict[str, Any]:
        """
        Extract response schema information from an operation

        Args:
            operation: OpenAPI operation object

        Returns:
            Response information dictionary
        """
        responses = operation.get("responses", {})
        response_info = {}

        # Extract 200 response (success)
        if "200" in responses:
            response_200 = responses["200"]
            response_info["description"] = response_200.get("description", "")

            # Extract JSON schema if present
            content = response_200.get("content", {})
            if "application/json" in content:
                json_content = content["application/json"]
                if "schema" in json_content:
                    response_info["schema"] = self._simplify_schema(json_content["schema"])

        return response_info

    def _add_common_query_params(self, input_schema: dict[str, Any]) -> None:
        """
        Add common query parameters like RQL, pagination, etc. if not already present

        Note: 'rql' is not actually a query parameter - it becomes the raw query string.
        The tool interface needs a parameter name, so we call it 'rql', but api_client.py
        extracts it and uses it as the query string directly (not as ?rql=...).

        Args:
            input_schema: The input schema to augment
        """
        properties = input_schema.get("properties", {})

        # Add 'rql' tool parameter (becomes the raw query string, not a query param)
        if "rql" not in properties:
            properties["rql"] = {
                "type": "string",
                "description": "RQL (Resource Query Language) query expression for filtering, sorting, and selecting fields. "
                "IMPORTANT: This is NOT a query parameter - it becomes the raw query string directly after '?'. "
                "Your value like 'eq(status,Failed)' becomes '/endpoint?eq(status,Failed)' NOT '/endpoint?rql=eq(...)'. "
                "\n\n"
                "OFFICIAL RQL SYNTAX (https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language):\n"
                "\n"
                "1. SIMPLE FILTERING: Use key=value for basic filtering\n"
                "   - 'status=Active' → /endpoint?status=Active\n"
                "   - 'firstName=John&lastName=Doe' → multiple filters\n"
                "\n"
                "2. COMPARISON OPERATORS (use parentheses):\n"
                "   - eq(field,value) - equals\n"
                "   - ne(field,value) - not equals\n"
                "   - gt(field,value) - greater than\n"
                "   - ge(field,value) - greater or equal\n"
                "   - lt(field,value) - less than\n"
                "   - le(field,value) - less or equal\n"
                "   - ilike(field,pattern) - case-insensitive search (use * as wildcard)\n"
                "   - in(field,(value1,value2,...)) - matches any value\n"
                "   - out(field,(value1,value2,...)) - matches none of the values\n"
                "\n"
                "3. LOGICAL OPERATORS:\n"
                "   - and(condition1,condition2,...) - all conditions must be true\n"
                "   - or(condition1,condition2,...) - at least one condition must be true\n"
                "   - not(condition) - negates the condition\n"
                "\n"
                "4. SORTING: Use order= (NOT sort!)\n"
                "   - order=+field - ascending (+ is optional)\n"
                "   - order=-field - descending\n"
                "   - order=+field1,-field2 - multiple fields\n"
                "\n"
                "5. PROJECTION: Use select= (NOT a function!)\n"
                "   - select=+field1,+field2 - include specific fields (+ is optional)\n"
                "   - select=-field1,-field2 - exclude specific fields\n"
                "   - select=audit - include the audit object (required for date fields!)\n"
                "\n"
                "6. PAGINATION:\n"
                "   - limit=10 - limit results\n"
                "   - offset=20 - skip first 20 records\n"
                "\n"
                "7. SPECIAL VALUES:\n"
                "   - empty() - represents empty string\n"
                "   - null() - represents null value\n"
                "\n"
                "8. SPECIAL CHARACTERS AND IDS:\n"
                '   - Enclose values with special chars in quotes: eq(name,"Buzz !!!")\n'
                '   - ID values (ACC-xxx, PRD-xxx, USR-xxx, etc.) MUST be in double quotes: eq(buyer.id,"ACC-4402-5918"), eq(client.id,"ACC-1234-5678")\n'
                "   - Unquoted IDs can return 0 results; always quote IDs in eq(...).\n"
                '   - Escape asterisk in ilike if literal: ilike(name,"The\\**")\n'
                "\n"
                "EXAMPLES:\n"
                "- Simple: 'status=Active&limit=10'\n"
                "- Search: 'ilike(name,*Teams*)&limit=20'\n"
                "- Sort: 'order=-name&select=id,name,status'\n"
                '- Filter by account ID: eq(buyer.id,"ACC-4402-5918") or eq(client.id,"ACC-1234-5678") (use schema to see which field exists)\n'
                "- Complex: 'and(eq(vendor.id,\"ACC-123\"),gt(audit.created,2024-11-01))&order=-audit.created&select=audit&limit=10'\n"
                "- Multiple conditions: 'and(eq(status,Failed),or(eq(type,A),eq(type,B)))'\n"
                "\n"
                "IMPORTANT: Date fields (created, updated) are in 'audit' object. Add '&select=audit' to access them!\n"
                "Filter fields must exist on the resource—use marketplace_resource_schema(resource) to see filterable fields (e.g. subscriptionsCount does not exist; for agreements with more than N subscriptions, fetch with select=+subscriptions.id,+subscriptions.name and filter/count in the response).",
            }

        # Add common pagination parameters if not present
        if "limit" not in properties:
            properties["limit"] = {
                "type": "integer",
                "description": "Maximum number of items to return (pagination). For large limits (e.g. 100, 500, 1000), use select= with only the fields you need (from marketplace_resource_schema); otherwise the response may cause a context limit error.",
            }

        if "offset" not in properties:
            properties["offset"] = {"type": "integer", "description": "Number of items to skip (pagination)"}

        if "page" not in properties:
            properties["page"] = {"type": "integer", "description": "Page number (alternative to offset)"}

        input_schema["properties"] = properties

    def _build_input_schema(self, path: str, parameters: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Build JSON schema for tool inputs from OpenAPI parameters

        Args:
            path: The API path
            parameters: OpenAPI parameters list

        Returns:
            JSON schema for input validation
        """
        properties = {}
        required = []

        for param in parameters:
            param_name = param.get("name")
            param_in = param.get("in")
            param_required = param.get("required", False)

            # Skip path parameters (they're part of the URL)
            if param_in == "path":
                continue

            # Skip header parameters (authentication handled by client)
            if param_in == "header":
                continue

            if not param_name:
                continue

            # Get parameter schema
            param_schema = param.get("schema", {})
            param_type = param_schema.get("type", "string")

            # Build property schema
            prop_schema = {
                "type": param_type,
                "description": param.get("description", f"Query parameter: {param_name}"),
            }

            # Add enum values if present
            if "enum" in param_schema:
                prop_schema["enum"] = param_schema["enum"]
                # Enhance description with valid values
                valid_values = ", ".join(str(v) for v in param_schema["enum"])
                prop_schema["description"] += f"\n\n**Valid values:** {valid_values}"

            # Add example if present
            if "example" in param_schema:
                prop_schema["example"] = param_schema["example"]
            elif "example" in param:
                prop_schema["example"] = param["example"]

            # Add format if present (e.g., date-time, uuid)
            if "format" in param_schema:
                prop_schema["format"] = param_schema["format"]

            # Add min/max constraints if present
            if "minimum" in param_schema:
                prop_schema["minimum"] = param_schema["minimum"]
            if "maximum" in param_schema:
                prop_schema["maximum"] = param_schema["maximum"]

            properties[param_name] = prop_schema

            if param_required:
                required.append(param_name)

        return {
            "properties": properties,
            "required": required,
        }

    def parse_openapi_for_endpoints(self, spec: dict[str, Any]) -> dict[str, Any]:
        """
        Parse OpenAPI spec and return structured endpoint information

        Args:
            spec: OpenAPI specification dictionary

        Returns:
            Dictionary with endpoint information
        """
        endpoints = {}
        paths = spec.get("paths", {})

        for path, path_item in paths.items():
            for method in ["get"]:
                if method not in path_item:
                    continue

                operation = path_item[method]
                operation_id = operation.get("operationId", f"{method.upper()}_{path}")

                endpoints[operation_id] = {
                    "method": method.upper(),
                    "path": path,
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "parameters": operation.get("parameters", []),
                    "responses": operation.get("responses", {}),
                }

        return endpoints

    async def create_tools_from_config(self, tools_config: list[dict[str, Any]]) -> list[Tool]:
        """
        Create MCP tools from manual configuration

        Args:
            tools_config: List of tool configuration dictionaries

        Returns:
            List of MCP Tool objects
        """
        tools = []

        for tool_def in tools_config:
            name = tool_def.get("name", "")
            path = tool_def.get("path", "")
            summary = tool_def.get("summary", "")
            parameters = tool_def.get("parameters", [])

            if not name or not path:
                continue

            # Sanitize the tool name
            name = self._sanitize_tool_name(name)

            # Build input schema
            input_schema = self._build_input_schema(path, parameters)

            # Build tool description
            tool_description = {
                "method": "GET",
                "path": path,
                "summary": summary,
                "parameters": parameters,
            }

            # Create MCP Tool
            tool = Tool(
                name=name,
                description=json.dumps(tool_description),
                inputSchema={
                    "type": "object",
                    "properties": input_schema.get("properties", {}),
                    "required": input_schema.get("required", []),
                },
            )

            tools.append(tool)

        return tools
