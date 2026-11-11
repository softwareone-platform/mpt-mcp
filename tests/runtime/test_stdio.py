import logging
from unittest.mock import Mock

import pytest
from fastmcp import FastMCP

from mpt_mcp.runtime import stdio


@pytest.fixture
def mcp_server(monkeypatch):
    server = Mock(spec=FastMCP)
    monkeypatch.setattr(stdio, "create_mcp_server", Mock(return_value=server))
    monkeypatch.setattr(stdio, "configure_logging", Mock())
    return server


def test_main_serves_stdio_without_banner(mcp_server):
    stdio.main()  # act

    stdio.create_mcp_server.assert_called_once_with(transport="stdio")
    mcp_server.run.assert_called_once_with(show_banner=False)


def test_main_warns_about_config_errors(mcp_server, monkeypatch, caplog):
    monkeypatch.setattr(stdio.config, "validate", Mock(return_value=["token missing"]))

    with caplog.at_level(logging.WARNING, logger="mpt_mcp.runtime.stdio"):
        stdio.main()  # act

    assert "Configuration error: token missing" in caplog.messages


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [(KeyboardInterrupt(), 0), (RuntimeError("boom"), 1)],
)
def test_main_exits_on_stop_or_error(mcp_server, error, exit_code):
    mcp_server.run.side_effect = error

    with pytest.raises(SystemExit) as exit_info:
        stdio.main()

    assert exit_info.value.code == exit_code
