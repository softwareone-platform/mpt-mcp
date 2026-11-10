from dataclasses import dataclass
from typing import Any

from mpt_mcp.marketplace.schemas import OpenAPISpec
from mpt_mcp.tools.query.paths import PATH_PARAM_PATTERN
from mpt_mcp.tools.responses import FilteringHints, ResourceSchemaResponse, SchemaField
from mpt_mcp.tools.results import tool_error
from mpt_mcp.tools.spec import MarketplaceSpec

EXAMPLE_LIMIT = 10
EXAMPLE_ORDER = "-audit.created.at"
MAX_ENUM_FILTERS = 3
MAX_NESTED_FIELDS = 5
MAX_SEARCH_FILTERS = 3
MAX_SELECT_FIELDS = 3
MAX_SIMPLE_FILTERS = 5
# Fields the select example lists first, when the resource has them
PREFERRED_SELECT_FIELDS = ("id", "name", "status")
# RQL compares these fields directly; objects and arrays get no filter hints
UNFILTERABLE_TYPES = frozenset(("array", "object", "unknown"))


def describe_resource_schema(resource: str, spec: MarketplaceSpec) -> ResourceSchemaResponse:
    """
    Describe the response of a resource: its schema, the fields of one item and filter hints.

    Args:
        resource: Resource name
        spec: OpenAPI spec of the endpoint, with its registry

    Returns:
        Response schema, item fields and RQL filter hints of the resource

    Raises:
        ToolError: The resource is unknown, or its path or GET operation is not in the spec
    """
    endpoint_path = spec.get_endpoint(resource)["path"]
    if endpoint_path not in (spec.openapi.document.get("paths") or {}):
        raise tool_error(f"Path {endpoint_path} not found in OpenAPI spec", resource=resource)

    operation = spec.openapi.get_operation(endpoint_path)
    if operation is None:
        raise tool_error(f"GET operation not found for {endpoint_path}", resource=resource)

    response_schema = spec.openapi.get_response_schema(operation)
    fields = None
    if response_schema is not None:
        fields = describe_item_fields(resource, spec)
    return ResourceSchemaResponse(
        resource=resource,
        path=endpoint_path,
        summary=operation.get("summary", ""),
        description=operation.get("description", ""),
        response_schema=response_schema,
        fields=fields,
        filtering_hints=None if fields is None else build_filtering_hints(fields),
        common_queries=QueryExamples(resource, endpoint_path, fields or {}).build(),
    )


@dataclass(frozen=True)
class QueryExamples:
    """marketplace_query calls for a resource, built from the fields of its items."""

    resource: str
    endpoint_path: str
    fields: dict[str, SchemaField]

    def build(self) -> dict[str, str]:
        """
        Build a plain call, and calls that filter, sort, select or do all of them.

        Returns:
            Calls by example name: basic, with_filters, with_sorting, with_select and
            full_example, each only when the fields allow it; resources that return a single
            item get no limit, filter or sort
        """
        all_options = {
            "with_filters": self._filter_option(),
            "with_sorting": self._sorting_option(),
            "with_select": self._select_option(),
        }
        options = {name: option for name, option in all_options.items() if option is not None}
        examples = {"basic": self._call()}
        examples |= {name: self._call(option) for name, option in options.items()}
        if len(options) > 1:
            examples["full_example"] = self._call(*options.values())
        return examples

    @property
    def _single_item(self) -> bool:
        return self.endpoint_path.endswith("}")

    def _call(self, *options: str) -> str:
        arguments = [f"resource='{self.resource}'"]
        path_params = {
            param_name: f"<{param_name}_value>"
            for param_name in PATH_PARAM_PATTERN.findall(self.endpoint_path)
        }
        if path_params:
            arguments.append(f"path_params={path_params}")
        arguments.extend(options)
        if not self._single_item:
            arguments.append(f"limit={EXAMPLE_LIMIT}")
        joined_arguments = ", ".join(arguments)
        return f"marketplace_query({joined_arguments})"

    def _filter_option(self) -> str | None:
        if self._single_item:
            return None

        enum_filters = [
            f"eq({field_name},{schema_field.enum[0]})"
            for field_name, schema_field in self.fields.items()
            if schema_field.enum
        ]
        return f"rql='{enum_filters[0]}'" if enum_filters else None

    def _select_option(self) -> str | None:
        scalar_fields = [
            field_name
            for field_name, schema_field in self.fields.items()
            if schema_field.type not in UNFILTERABLE_TYPES
        ]
        ordered = [
            field_name for field_name in PREFERRED_SELECT_FIELDS if field_name in scalar_fields
        ] + [
            field_name for field_name in scalar_fields if field_name not in PREFERRED_SELECT_FIELDS
        ]
        if not ordered:
            return None

        select = ",".join(f"+{field_name}" for field_name in ordered[:MAX_SELECT_FIELDS])
        return f"select='-*,{select}'"

    def _sorting_option(self) -> str | None:
        if self._single_item or "audit" not in self.fields:
            return None

        return f"order='{EXAMPLE_ORDER}'"


def build_filtering_hints(fields: dict[str, SchemaField]) -> FilteringHints:
    """
    Build RQL filters from the fields of a resource item.

    Args:
        fields: Top-level fields of one item

    Returns:
        Equality filters on scalar fields, text searches on string fields and enum filters
    """
    scalar_fields = [
        field_name
        for field_name, schema_field in fields.items()
        if schema_field.type not in UNFILTERABLE_TYPES
    ]
    return FilteringHints(
        simple_filters=[
            f"eq({field_name},value)" for field_name in scalar_fields[:MAX_SIMPLE_FILTERS]
        ],
        search_fields=[
            f"ilike({field_name},*keyword*)"
            for field_name in scalar_fields
            if fields[field_name].type == "string"
        ][:MAX_SEARCH_FILTERS],
        enum_filters=[
            f"eq({field_name},{schema_field.enum[0]})"
            for field_name, schema_field in fields.items()
            if schema_field.enum is not None
        ][:MAX_ENUM_FILTERS],
    )


def describe_field(openapi: OpenAPISpec, declared_schema: dict[str, Any]) -> SchemaField:
    """
    Describe one field of a resource item.

    Args:
        openapi: OpenAPI spec of the endpoint, to resolve the field schema
        declared_schema: Schema of the field as the item declares it, maybe a $ref or allOf

    Returns:
        Type, description, enum values, example, format and nested fields of the field
    """
    field_schema = openapi.resolve_schema(declared_schema)
    field_enum = field_schema.get("enum")
    nested_properties = field_schema.get("properties")
    untyped = "object" if "properties" in field_schema else "unknown"
    return SchemaField(
        type=field_schema.get("type") or untyped,
        description=declared_schema.get("description") or field_schema.get("description", ""),
        enum=field_enum,
        valid_values=field_enum,
        example=field_schema.get("example"),
        format=field_schema.get("format"),
        nested_fields=None
        if nested_properties is None
        else describe_nested_fields(nested_properties),
    )


def describe_item_fields(resource: str, spec: MarketplaceSpec) -> dict[str, SchemaField] | None:
    """
    Describe the top-level fields of one item of a resource.

    Args:
        resource: Resource name
        spec: OpenAPI spec of the endpoint, with its registry

    Returns:
        Fields by name, or None when the item schema has no properties
    """
    item_properties = spec.get_item_schema(resource).get("properties")
    if item_properties is None:
        return None

    return {
        field_name: describe_field(spec.openapi, declared_schema)
        for field_name, declared_schema in item_properties.items()
    }


def describe_nested_fields(
    nested_properties: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return the type and description of the first MAX_NESTED_FIELDS fields of an object."""
    first_fields = list(nested_properties.items())[:MAX_NESTED_FIELDS]
    return {
        nested_name: {
            "type": nested_schema.get("type", "unknown"),
            "description": nested_schema.get("description", ""),
        }
        for nested_name, nested_schema in first_fields
    }
