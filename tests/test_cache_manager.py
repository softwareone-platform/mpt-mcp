import datetime as dt

from mpt_mcp.cache_manager import read_cached_at

CACHED_AT_UTC = dt.datetime.fromisoformat("2026-11-02T11:41:47+00:00")


def test_read_cached_at_reads_naive_time_as_utc():
    result = read_cached_at("2026-11-02T11:41:47")

    assert result == CACHED_AT_UTC


def test_read_cached_at_keeps_time_zone():
    result = read_cached_at("2026-11-02T12:41:47+01:00")

    assert result == CACHED_AT_UTC
    assert result.utcoffset() == dt.timedelta(hours=1)
