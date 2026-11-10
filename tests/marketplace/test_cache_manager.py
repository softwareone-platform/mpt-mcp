import datetime as dt
import json
from http import HTTPStatus
from unittest.mock import Mock

import httpx
import pytest

from mpt_mcp.marketplace.cache_manager import CacheManager, fetch_with_cache, read_cached_at

CACHED_AT_UTC = dt.datetime.fromisoformat("2026-11-02T11:41:47+00:00")
SPEC_URL = "https://api.test.com/public/v1/openapi.json"
OTHER_SPEC_URL = "https://api.other.com/public/v1/openapi.json"


def test_read_cached_at_reads_naive_time_as_utc():
    result = read_cached_at("2026-11-02T11:41:47")

    assert result == CACHED_AT_UTC


def test_read_cached_at_keeps_time_zone():
    result = read_cached_at("2026-11-02T12:41:47+01:00")

    assert result == CACHED_AT_UTC
    assert result.utcoffset() == dt.timedelta(hours=1)


@pytest.fixture
def cache_manager(tmp_path):
    return CacheManager(cache_dir=str(tmp_path / "cache"), ttl_hours=24)


@pytest.fixture
def expire_entry(cache_manager):
    def factory(key):
        meta_path = cache_manager.get_cache_path(key).with_suffix(".meta.json")
        expired_for = cache_manager.ttl + dt.timedelta(hours=1)
        expired_at = dt.datetime.now(dt.UTC) - expired_for
        meta_path.write_text(json.dumps({"cached_at": expired_at.isoformat()}), encoding="utf-8")

    return factory


@pytest.fixture
def http_responder(monkeypatch):
    def factory(respond):
        original_client = httpx.AsyncClient
        monkeypatch.setattr(
            "mpt_mcp.marketplace.cache_manager.httpx.AsyncClient",
            lambda **client_args: original_client(
                **client_args, transport=httpx.MockTransport(respond)
            ),
        )

    return factory


@pytest.fixture
def spec_document():
    return {"openapi": "3.0.0"}


def test_set_then_get_returns_data(cache_manager, spec_document):
    cache_manager.set(SPEC_URL, spec_document)

    result = cache_manager.get(SPEC_URL)

    assert result == spec_document


def test_get_missing_entry(cache_manager):
    result = cache_manager.get(SPEC_URL)

    assert result is None


def test_get_expired_entry(cache_manager, expire_entry, spec_document):
    cache_manager.set(SPEC_URL, spec_document)
    expire_entry(SPEC_URL)

    result = cache_manager.get(SPEC_URL)

    assert result is None


@pytest.mark.parametrize("meta_text", ["{}", '{"cached_at": "yesterday"}'])
def test_get_entry_with_bad_metadata(cache_manager, meta_text, spec_document):
    cache_manager.set(SPEC_URL, spec_document)
    meta_path = cache_manager.get_cache_path(SPEC_URL).with_suffix(".meta.json")
    meta_path.write_text(meta_text, encoding="utf-8")

    result = cache_manager.get(SPEC_URL)

    assert result is None


def test_get_entry_with_bad_json(cache_manager, spec_document):
    cache_manager.set(SPEC_URL, spec_document)
    cache_manager.get_cache_path(SPEC_URL).write_text("{not json", encoding="utf-8")

    result = cache_manager.get(SPEC_URL)

    assert result is None


def test_invalidate_removes_entry(cache_manager, spec_document):
    cache_manager.set(SPEC_URL, spec_document)

    cache_manager.invalidate(SPEC_URL)  # act

    assert list(cache_manager.cache_dir.iterdir()) == []


def test_get_cache_info_counts_entries(cache_manager, expire_entry, spec_document):
    cache_manager.set(SPEC_URL, spec_document)
    cache_manager.set(OTHER_SPEC_URL, spec_document)
    expire_entry(OTHER_SPEC_URL)

    result = cache_manager.get_cache_info()

    counts = (result["total_entries"], result["valid_entries"], result["expired_entries"])
    assert counts == (2, 1, 1)
    assert result["ttl_hours"] == 24
    assert result["total_size_bytes"] > 0


async def test_fetch_uses_valid_cache(cache_manager, http_responder):
    cache_manager.set(SPEC_URL, {"openapi": "cached"})
    http_responder(Mock(side_effect=AssertionError("no request expected")))

    result = await fetch_with_cache(SPEC_URL, cache_manager)

    assert result == {"openapi": "cached"}


async def test_fetch_force_refresh_stores_new_data(cache_manager, http_responder):
    cache_manager.set(SPEC_URL, {"openapi": "cached"})
    http_responder(lambda request: httpx.Response(HTTPStatus.OK, json={"openapi": "fresh"}))

    result = await fetch_with_cache(SPEC_URL, cache_manager, force_refresh=True)

    assert result == {"openapi": "fresh"}
    assert cache_manager.get(SPEC_URL) == {"openapi": "fresh"}


async def test_fetch_failure_uses_expired_cache(cache_manager, http_responder, expire_entry):
    cache_manager.set(SPEC_URL, {"openapi": "stale"})
    expire_entry(SPEC_URL)
    http_responder(lambda request: httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE))

    result = await fetch_with_cache(SPEC_URL, cache_manager)

    assert result == {"openapi": "stale"}


async def test_fetch_failure_without_cache_raises(cache_manager, http_responder):
    http_responder(lambda request: httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_with_cache(SPEC_URL, cache_manager)
