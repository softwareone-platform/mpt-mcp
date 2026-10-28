import pytest

from mpt_mcp.config import config


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [("gitbook_api_base_url", "https://api.gitbook.com/v1"), ("gitbook_cache_refresh_hours", 24)],
)
def test_config_default_values(attribute, expected):
    result = getattr(config, attribute)

    assert result == expected


def test_http_settings_have_valid_values():
    result = (config.sse_host, config.sse_port, config.sse_cors_origins)

    assert result[0] in {"0.0.0.0", "localhost", "127.0.0.1"}
    assert 1000 <= result[1] <= 65535
    assert result[2]
