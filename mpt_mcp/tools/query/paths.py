import difflib
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from mpt_mcp.tools.results import tool_error

if TYPE_CHECKING:
    from collections.abc import Iterable

PATH_PARAM_EXAMPLES = MappingProxyType({
    "id": "PRD-1234-5678",
    "productId": "PRD-1234-5678",
    "orderId": "ORD-1234-5678-9012",
    "agreementId": "AGR-1234-5678-9012",
    "subscriptionId": "SUB-1234-5678-9012",
    "accountId": "ACC-1234-5678",
    "userId": "USR-1234-5678",
    "lineId": "LIN-1234-5678",
    "assetId": "AST-1234-5678",
})
PATH_PARAM_PATTERN = re.compile(r"\{(\w+)\}")
# Suggestions for an unknown resource: how many, and how close a misspelled name must be (0-1)
SUGGESTION_COUNT = 5
SUGGESTION_SIMILARITY = 0.6


def get_endpoint_path(resource: str, endpoints_registry: dict[str, Any]) -> str:
    """
    Return the API path template of a resource.

    Args:
        resource: Resource name, e.g. commerce.orders
        endpoints_registry: Registry of available endpoints

    Returns:
        API path with its path parameters in braces, e.g. /public/v1/commerce/orders/{orderId}

    Raises:
        ToolError: The resource is unknown; the error suggests similar resources
    """
    endpoint = endpoints_registry.get(resource)
    if endpoint is not None:
        endpoint_path: str = endpoint["path"]
        return endpoint_path

    hints: dict[str, Any] = {
        "hint": "Use marketplace_resources() to see all available resources",
        "available_categories": list({known.split(".")[0] for known in endpoints_registry}),
    }
    similar_resources = suggest_resources(resource, endpoints_registry)
    if similar_resources:
        hints["did_you_mean"] = similar_resources

    raise tool_error(f"Unknown resource: '{resource}'", **hints)


def fill_path_params(resource: str, endpoint_path: str, path_params: dict[str, str] | None) -> str:
    """
    Replace the path parameters of an API path template with their values.

    Args:
        resource: Resource name, used in the example of the error
        endpoint_path: API path template, e.g. /public/v1/commerce/orders/{orderId}
        path_params: Values by parameter name

    Returns:
        API path with every parameter replaced

    Raises:
        ToolError: A path parameter has no value; the error shows a call that gives it
    """
    api_path = endpoint_path
    for param_name, param_value in (path_params or {}).items():
        api_path = api_path.replace(f"{{{param_name}}}", str(param_value))

    missing_params = PATH_PARAM_PATTERN.findall(api_path)
    if not missing_params:
        return api_path

    example_dict = {
        missing_param: PATH_PARAM_EXAMPLES.get(missing_param, f"<{missing_param}_value>")
        for missing_param in missing_params
    }
    hint_dict = ", ".join(
        f"'{missing_param}': '{PATH_PARAM_EXAMPLES.get(missing_param, 'value')}'"
        for missing_param in missing_params
    )
    required_params = ", ".join(missing_params)
    raise tool_error(
        f"This resource requires path parameters: {required_params}",
        resource=resource,
        path_template=endpoint_path,
        example=f"marketplace_query(resource='{resource}', path_params={example_dict}, limit=10)",
        hint=f"You must provide path_params dictionary. For example: path_params={{{hint_dict}}}",
    )


def suggest_resources(resource: str, resources: Iterable[str]) -> list[str]:
    """
    Suggest known resources for an unknown resource name.

    Resources that contain the name, or are contained in it, come first, closest spelling first;
    then resources with a similar spelling, so typos such as catalog.prodcts still get a suggestion.

    Args:
        resource: Unknown resource name, e.g. catalog.prodcts
        resources: Known resource IDs

    Returns:
        Up to SUGGESTION_COUNT resource IDs, best matches first
    """
    resource_lower = resource.lower()
    resources_by_lower = {known.lower(): known for known in resources}
    containing = sorted(
        (
            known_lower
            for known_lower in resources_by_lower
            if resource_lower in known_lower or known_lower in resource_lower
        ),
        key=lambda known_lower: -difflib.SequenceMatcher(None, resource_lower, known_lower).ratio(),
    )
    similar = [
        resources_by_lower[known_lower]
        for known_lower in difflib.get_close_matches(
            resource_lower, resources_by_lower, n=SUGGESTION_COUNT, cutoff=SUGGESTION_SIMILARITY
        )
    ]
    containing_resources = [resources_by_lower[known_lower] for known_lower in containing]
    return list(dict.fromkeys(containing_resources + similar))[:SUGGESTION_COUNT]
