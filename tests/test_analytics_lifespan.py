"""Tests for analytics ASGI lifespan wiring (issue #9).

Analytics must be initialized inside the ASGI lifespan (on the serving loop), NOT at
import time on a throwaway asyncio loop. These tests assert that wiring without needing
a live database.
"""

from unittest.mock import AsyncMock

import src.server


def test_import_does_not_initialize_analytics_at_import_time():
    """Importing src.server must NOT run analytics init: the logger is only created by
    the lifespan on startup, so with no lifespan run yet it must be None."""
    assert src.server.get_analytics_logger() is None


async def test_analytics_lifespan_initializes_on_enter_and_closes_on_exit(monkeypatch):
    """The lifespan context manager must await initialize_analytics on enter and
    await close() on exit."""
    init_mock = AsyncMock()
    close_mock = AsyncMock()
    fake_logger = AsyncMock()
    fake_logger.close = close_mock

    monkeypatch.setattr(src.server, "initialize_analytics", init_mock)
    monkeypatch.setattr(src.server, "get_analytics_logger", lambda: fake_logger)

    async with src.server._analytics_lifespan(None):
        # initialize must have been awaited on entry
        init_mock.assert_awaited_once()
        close_mock.assert_not_awaited()

    # close must have been awaited on exit
    close_mock.assert_awaited_once()


async def test_analytics_lifespan_closes_even_without_logger(monkeypatch):
    """If no logger is available on shutdown, the lifespan must exit cleanly."""
    init_mock = AsyncMock()
    monkeypatch.setattr(src.server, "initialize_analytics", init_mock)
    monkeypatch.setattr(src.server, "get_analytics_logger", lambda: None)

    async with src.server._analytics_lifespan(None):
        pass

    init_mock.assert_awaited_once()
