#!/usr/bin/env python3
"""
Test endpoint validation and normalization
"""

import pytest

from src.server import normalize_endpoint_url


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
