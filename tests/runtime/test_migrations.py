import logging
from unittest.mock import Mock

import pytest

from mpt_mcp.runtime import migrations


@pytest.fixture
def upgrade(monkeypatch):
    upgrade_mock = Mock()
    monkeypatch.setattr(migrations.command, "upgrade", upgrade_mock)
    return upgrade_mock


def test_run_migrations_skipped_without_analytics(monkeypatch, upgrade):
    monkeypatch.setattr(migrations.config, "analytics_database_url", "")

    migrations.run_migrations()  # act

    upgrade.assert_not_called()


def test_run_migrations_upgrades_with_sync_url(monkeypatch, upgrade):
    monkeypatch.setattr(
        migrations.config, "analytics_database_url", "postgresql+asyncpg://user@db/analytics"
    )

    migrations.run_migrations()  # act

    alembic_cfg, revision = upgrade.call_args.args
    assert revision == "head"
    assert alembic_cfg.get_main_option("sqlalchemy.url") == "postgresql://user@db/analytics"
    assert alembic_cfg.attributes["configure_logger"] is False


def test_run_migrations_logs_failure(monkeypatch, upgrade, caplog):
    monkeypatch.setattr(migrations.config, "analytics_database_url", "postgresql://db/analytics")
    upgrade.side_effect = RuntimeError("database down")

    with caplog.at_level(logging.WARNING, logger="mpt_mcp.runtime.migrations"):
        migrations.run_migrations()  # act

    assert "Migration warning: database down" in caplog.messages
