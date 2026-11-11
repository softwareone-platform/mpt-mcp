import pytest

from mpt_mcp.config import config


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [("gitbook_api_base_url", "https://api.gitbook.com/v1"), ("gitbook_cache_refresh_hours", 24)],
)
def test_config_default_values(attribute, expected):
    result = getattr(config, attribute)

    assert result == expected
