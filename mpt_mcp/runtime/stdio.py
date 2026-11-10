import logging
import sys

from mpt_mcp.config import config
from mpt_mcp.runtime.logging import configure_logging
from mpt_mcp.server import create_mcp_server

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the stdio server: report configuration errors and serve MCP on stdin and stdout."""
    configure_logging(logging.DEBUG if config.debug else logging.INFO)
    mcp = create_mcp_server(transport="stdio")
    logger.info("=" * 60)
    logger.info("SoftwareOne Marketplace MCP Server (Stdio Mode)")
    logger.info("=" * 60)
    for config_error in config.validate():
        logger.warning("Configuration error: %s", config_error)
    logger.info("API endpoint: %s", config.marketplace_api_base_url)
    logger.info("Starting server on stdio...")
    logger.info("=" * 60)

    try:
        mcp.run(show_banner=False)
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        sys.exit(0)
    except Exception:
        logger.exception("Server error")
        sys.exit(1)


if __name__ == "__main__":
    main()
