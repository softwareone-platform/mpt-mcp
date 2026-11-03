import logging

from mpt_mcp.config import config
from mpt_mcp.runtime.http import create_http_app
from mpt_mcp.runtime.logging import configure_logging
from mpt_mcp.server import create_mcp_server

# uvicorn imports this module in every worker, and again on each reload
configure_logging(logging.DEBUG if config.debug else logging.INFO)

app = create_http_app(create_mcp_server(transport="http"))
