import logging

import pytest

from mpt_mcp.log_config import RequestContextFilter, current_session_id, current_user_id


@pytest.fixture
def log_record():
    return logging.LogRecord("mpt_mcp.test", logging.INFO, __file__, 1, "message", None, None)


@pytest.fixture
def request_context():
    tokens = []

    def _request_context(session_id, user_id):
        tokens.append((current_session_id.set(session_id), current_user_id.set(user_id)))

    yield _request_context
    for session_token, user_token in reversed(tokens):
        current_session_id.reset(session_token)
        current_user_id.reset(user_token)


@pytest.mark.parametrize(
    ("session_id", "user_id", "expected"),
    [
        ("abcdef123456", "TKN-1234-5678", "[sess:abcdef12|user:TKN-1234-5678] "),
        (None, "TKN-1234-5678", "[user:TKN-1234-5678] "),
        ("abcdef123456", None, "[sess:abcdef12] "),
        (None, None, ""),
    ],
)
def test_filter_adds_request_context_prefix(log_record, request_context, session_id, user_id, expected):
    request_context(session_id, user_id)

    RequestContextFilter().filter(log_record)  # act

    assert log_record.request_context == expected
