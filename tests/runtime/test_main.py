from starlette.applications import Starlette

from mpt_mcp.runtime import main


def test_app_serves_mcp_and_health():
    result = main.app

    assert isinstance(result, Starlette)
    assert {"/mcp", "/health", "/"} <= {route.path for route in result.routes}
