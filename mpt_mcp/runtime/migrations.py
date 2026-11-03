import logging
import pathlib

from alembic.config import Config as AlembicConfig

from alembic import command
from mpt_mcp.config import config

logger = logging.getLogger(__name__)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent


def run_migrations() -> None:
    """Apply the analytics database migrations when analytics is configured."""
    if not config.analytics_database_url:
        logger.info("Skipping migrations (analytics not configured)")
        return

    try:
        logger.info("Running database migrations...")
        alembic_cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        # Keep the server logging setup: alembic/env.py only configures logging for the alembic CLI
        alembic_cfg.attributes["configure_logger"] = False
        sync_url = config.analytics_database_url.replace("postgresql+asyncpg://", "postgresql://")
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
    except Exception as error:
        logger.warning("Migration warning: %s", error)
        logger.info("Server will continue, but analytics may not work correctly")
