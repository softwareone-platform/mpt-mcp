#!/usr/bin/env python3
"""
Test endpoint validation and normalization
"""

import pytest

import src.server_context as server_context
from src.server_context import (
    get_current_credentials,
    normalize_endpoint_url,
    validate_endpoint_url,
)


class TestEndpointNormalization:
    """Test URL normalization for API endpoints"""

    @pytest.mark.parametrize(
        "input_url,expected",
        [
            ("https://api.s1.show/public", "https://api.s1.show"),
            ("https://api.platform.softwareone.com/public", "https://api.platform.softwareone.com"),
            ("https://api.s1.show/public/", "https://api.s1.show"),
            ("https://api.s1.show", "https://api.s1.show"),
            ("https://api.s1.show/", "https://api.s1.show"),
            ("http://localhost:8080/public", "http://localhost:8080"),
        ],
    )
    def test_normalize_endpoint_removes_public_suffix(self, input_url, expected):
        """Test that /public suffix is removed from endpoints"""
        result = normalize_endpoint_url(input_url)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_normalize_endpoint_preserves_valid_urls(self):
        """Test that already-correct URLs are preserved"""
        url = "https://api.example.com"
        result = normalize_endpoint_url(url)
        assert result == url

    def test_normalize_endpoint_handles_trailing_slash(self):
        """Test that trailing slashes are removed"""
        assert normalize_endpoint_url("https://api.s1.show/") == "https://api.s1.show"
        assert normalize_endpoint_url("https://api.s1.show//") == "https://api.s1.show"


# Note: Endpoint validation was removed in HTTP server refactor
# The server now validates on-demand when credentials are provided


@pytest.mark.unit
class TestEndpointNormalizationEdgeCases:
    """Test edge cases for URL normalization"""

    def test_normalize_empty_string(self):
        """Test handling of empty string"""
        result = normalize_endpoint_url("")
        assert result == ""

    def test_normalize_only_public(self):
        """Test handling of just /public"""
        result = normalize_endpoint_url("/public")
        assert result == ""

    def test_normalize_preserves_paths_other_than_public(self):
        """Test that other paths are preserved"""
        url = "https://api.example.com/api/v1"
        result = normalize_endpoint_url(url)
        assert result == url

    def test_normalize_case_sensitive(self):
        """Test that normalization is case-sensitive for /public"""
        # /Public (capitalized) should NOT be removed
        url = "https://api.example.com/Public"
        result = normalize_endpoint_url(url)
        assert result == url  # Should not be modified


class TestEndpointUrlValidation:
    """Test SSRF/credential-exfil protection for the client-supplied X-MPT-Endpoint header"""

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.platform.softwareone.com",
            "https://softwareone.com",
            "https://api.staging.platform.softwareone.com",
        ],
    )
    def test_allowed_hosts_are_valid(self, url):
        """Allowlisted hosts and their subdomains are accepted"""
        is_valid, error = validate_endpoint_url(url)
        assert is_valid is True
        assert error is None

    def test_http_scheme_rejected(self):
        """Non-https schemes are rejected"""
        is_valid, error = validate_endpoint_url("http://api.platform.softwareone.com")
        assert is_valid is False
        assert error == "endpoint must use https"

    def test_foreign_host_rejected(self):
        """A host outside the allowlist is rejected"""
        is_valid, error = validate_endpoint_url("https://evil.example.com")
        assert is_valid is False
        assert error == "endpoint host not in allowlist"

    def test_metadata_ip_rejected(self):
        """The cloud metadata IP (link-local) is rejected"""
        is_valid, error = validate_endpoint_url("https://169.254.169.254/latest/meta-data")
        assert is_valid is False
        assert error == "endpoint host not allowed"

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1",
            "https://10.0.0.5",
        ],
    )
    def test_private_and_loopback_ips_rejected(self, url):
        """Private and loopback IP literals are rejected"""
        is_valid, error = validate_endpoint_url(url)
        assert is_valid is False
        assert error == "endpoint host not allowed"


class TestGetCurrentCredentialsValidation:
    """Test that get_current_credentials enforces endpoint validation"""

    def test_invalid_endpoint_header_raises(self):
        """A client-supplied invalid endpoint header causes a ValueError"""
        token_tok = server_context._current_token.set("test-token")
        endpoint_tok = server_context._current_endpoint.set("https://evil.example.com")
        try:
            with pytest.raises(ValueError, match="Invalid X-MPT-Endpoint"):
                get_current_credentials()
        finally:
            server_context._current_token.reset(token_tok)
            server_context._current_endpoint.reset(endpoint_tok)

    def test_valid_endpoint_header_accepted(self):
        """A client-supplied allowlisted endpoint header is accepted"""
        token_tok = server_context._current_token.set("test-token")
        endpoint_tok = server_context._current_endpoint.set("https://api.platform.softwareone.com/public")
        try:
            token, endpoint = get_current_credentials()
            assert token == "test-token"
            assert endpoint == "https://api.platform.softwareone.com"
        finally:
            server_context._current_token.reset(token_tok)
            server_context._current_endpoint.reset(endpoint_tok)

    def test_no_endpoint_header_uses_trusted_default(self):
        """When no endpoint header is provided, the trusted default is used without raising"""
        token_tok = server_context._current_token.set("test-token")
        try:
            token, endpoint = get_current_credentials()
            assert token == "test-token"
            assert endpoint == normalize_endpoint_url(server_context.config.sse_default_base_url)
        finally:
            server_context._current_token.reset(token_tok)
