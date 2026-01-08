"""
Test API client URL normalization

The API client normalizes base URLs to extract only scheme://hostname[:port]
This prevents path duplication when OpenAPI paths are absolute.
"""

import pytest
from src.api_client import APIClient


def test_api_client_strips_public_path():
    """Test that base URL with /public path is stripped to hostname"""
    client = APIClient(
        base_url="https://api.s1.show/public",
        token="test-token"
    )
    assert client.base_url == "https://api.s1.show"


def test_api_client_strips_trailing_slash():
    """Test that base URL with trailing slash is stripped to hostname"""
    client = APIClient(
        base_url="https://api.platform.softwareone.com/",
        token="test-token"
    )
    assert client.base_url == "https://api.platform.softwareone.com"


def test_api_client_strips_any_path():
    """Test that any path is stripped, not just /public"""
    client = APIClient(
        base_url="https://api.s1.show/v1/api/anything",
        token="test-token"
    )
    assert client.base_url == "https://api.s1.show"


def test_api_client_preserves_hostname_only_url():
    """Test that hostname-only URL is preserved"""
    client = APIClient(
        base_url="https://api.platform.softwareone.com",
        token="test-token"
    )
    assert client.base_url == "https://api.platform.softwareone.com"


def test_api_client_preserves_port():
    """Test that port number is preserved"""
    client = APIClient(
        base_url="http://localhost:8080/some/path",
        token="test-token"
    )
    assert client.base_url == "http://localhost:8080"


def test_api_client_handles_http_protocol():
    """Test that http:// protocol is handled correctly"""
    client = APIClient(
        base_url="http://api.example.com/path",
        token="test-token"
    )
    assert client.base_url == "http://api.example.com"


def test_api_client_constructs_correct_url():
    """Test that URLs are constructed correctly after normalization"""
    client = APIClient(
        base_url="https://api.s1.show/public",
        token="test-token"
    )
    
    # Simulate URL construction (same logic as in get method)
    endpoint = "/public/v1/catalog/products"
    url = f"{client.base_url}{endpoint}"
    
    # Should not have double /public
    assert url == "https://api.s1.show/public/v1/catalog/products"
    assert "/public/public/" not in url


def test_api_client_prevents_path_duplication():
    """Test that various base URLs prevent path duplication"""
    test_cases = [
        ("https://api.s1.show/public", "/public/v1/catalog/products", "https://api.s1.show/public/v1/catalog/products"),
        ("https://api.s1.show/v1", "/public/v1/catalog/products", "https://api.s1.show/public/v1/catalog/products"),
        ("https://api.s1.show", "/public/v1/catalog/products", "https://api.s1.show/public/v1/catalog/products"),
    ]
    
    for base_url, endpoint, expected_url in test_cases:
        client = APIClient(base_url=base_url, token="test-token")
        url = f"{client.base_url}{endpoint}"
        assert url == expected_url, f"Failed for base_url={base_url}, endpoint={endpoint}"


def test_api_client_handles_subdomain():
    """Test that subdomains are preserved"""
    client = APIClient(
        base_url="https://api.staging.platform.softwareone.com/public/v1",
        token="test-token"
    )
    assert client.base_url == "https://api.staging.platform.softwareone.com"

