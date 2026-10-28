import os
from unittest.mock import Mock

import pytest

from mpt_mcp import server_docs


@pytest.fixture
def gitbook_not_configured(monkeypatch):
    monkeypatch.setattr(server_docs.config, "gitbook_api_key", "")
    monkeypatch.setattr(server_docs.config, "gitbook_space_id", "")


@pytest.mark.usefixtures("gitbook_not_configured")
async def test_init_docs_cache_disabled_without_gitbook():
    await server_docs.initialize_documentation_cache()  # act

    assert server_docs.documentation_cache.is_enabled is False


@pytest.mark.usefixtures("gitbook_not_configured")
async def test_init_docs_cache_again_in_new_process(monkeypatch):
    await server_docs.initialize_documentation_cache()
    stale_cache = Mock()
    monkeypatch.setattr(server_docs, "documentation_cache", stale_cache)
    other_pid = os.getpid() + 1
    monkeypatch.setattr(server_docs.os, "getpid", Mock(return_value=other_pid))

    await server_docs.initialize_documentation_cache()  # act

    assert server_docs.documentation_cache is not stale_cache
