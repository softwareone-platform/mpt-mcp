import re
from types import MappingProxyType

from mpt_mcp.tools.results import tool_error

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


def fill_path_params(resource: str, endpoint_path: str, path_params: dict[str, str] | None) -> str:  # noqa: WPS210
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
