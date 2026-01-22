"""
Test API client token handling and user identification
"""

from src.api_client import APIClient


class TestBearerTokenHandling:
    """Test that Bearer token prefix is handled correctly"""

    def test_token_without_bearer_gets_prefix_added(self):
        """Test that token without Bearer prefix gets it added"""
        client = APIClient(base_url="https://api.example.com", token="my-token-value")
        assert client.token == "Bearer my-token-value"

    def test_token_with_bearer_stays_unchanged(self):
        """Test that token with Bearer prefix is not modified"""
        client = APIClient(base_url="https://api.example.com", token="Bearer my-token-value")
        assert client.token == "Bearer my-token-value"

    def test_bearer_with_mixed_case(self):
        """Test that only 'Bearer ' (capital B) is recognized"""
        # Lowercase 'bearer' should get Bearer prefix added
        client = APIClient(base_url="https://api.example.com", token="bearer my-token")
        assert client.token == "Bearer bearer my-token"

    def test_token_with_special_characters(self):
        """Test that special characters in token are preserved"""
        token = "idt:TKN-1234-5678:abc123XYZ_-."
        client = APIClient(base_url="https://api.example.com", token=token)
        assert client.token == f"Bearer {token}"

    def test_headers_use_normalized_token(self):
        """Test that headers use the normalized token with Bearer prefix"""
        client = APIClient(base_url="https://api.example.com", token="my-token")
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer my-token"


class TestUserIdentificationExtraction:
    """Test user ID extraction from tokens"""

    def test_extract_user_id_from_idt_token(self):
        """Test extracting user ID from standard idt token format"""
        token = "idt:TKN-0291-1452:4l6Fq7jrGSfZVjDYHabJkxTuv4nynuj5f8qVTbbHJS5rFXpetnvRYfvwiaRjGzrF"
        client = APIClient(base_url="https://api.example.com", token=token)
        assert client.user_id == "TKN-0291-1452"

    def test_extract_user_id_from_token_with_bearer(self):
        """Test extracting user ID when token has Bearer prefix"""
        token = "Bearer idt:TKN-1234-5678:abc123"
        client = APIClient(base_url="https://api.example.com", token=token)
        assert client.user_id == "TKN-1234-5678"

    def test_extract_user_id_with_different_tkn_format(self):
        """Test extracting user ID with different TKN number formats"""
        test_cases = [
            ("idt:TKN-0000-0000:token", "TKN-0000-0000"),
            ("idt:TKN-9999-9999:token", "TKN-9999-9999"),
            ("idt:TKN-1111-2222:token", "TKN-1111-2222"),
        ]

        for token, expected_user_id in test_cases:
            client = APIClient(base_url="https://api.example.com", token=token)
            assert client.user_id == expected_user_id

    def test_no_user_id_for_non_idt_token(self):
        """Test that non-idt tokens return None for user_id"""
        tokens = [
            "simple-token",
            "Bearer simple-token",
            "jwt.token.here",
            "api-key-12345",
        ]

        for token in tokens:
            client = APIClient(base_url="https://api.example.com", token=token)
            assert client.user_id is None

    def test_no_user_id_for_malformed_idt_token(self):
        """Test that malformed idt tokens return None"""
        malformed_tokens = [
            "idt:TOKEN-123:value",  # Wrong format (TOKEN instead of TKN)
            "idt:TKN-123",  # Missing third part
            "idt:",  # Incomplete
            "TKN-1234-5678:token",  # Missing idt: prefix
        ]

        for token in malformed_tokens:
            client = APIClient(base_url="https://api.example.com", token=token)
            assert client.user_id is None

    def test_user_id_extraction_static_method(self):
        """Test the _extract_user_id static method directly"""
        # Valid tokens
        assert APIClient._extract_user_id("idt:TKN-1234-5678:token") == "TKN-1234-5678"
        assert APIClient._extract_user_id("Bearer idt:TKN-1234-5678:token") == "TKN-1234-5678"

        # Invalid tokens
        assert APIClient._extract_user_id("simple-token") is None
        assert APIClient._extract_user_id("idt:TOKEN-123:value") is None
        assert APIClient._extract_user_id("TKN-1234-5678") is None


class TestCombinedFeatures:
    """Test Bearer prefix + user ID extraction working together"""

    def test_idt_token_without_bearer_gets_prefix_and_user_id(self):
        """Test that idt token without Bearer gets both features applied"""
        token = "idt:TKN-1234-5678:secret"
        client = APIClient(base_url="https://api.example.com", token=token)

        # Should have Bearer prefix added
        assert client.token == f"Bearer {token}"

        # Should have user_id extracted
        assert client.user_id == "TKN-1234-5678"

    def test_idt_token_with_bearer_keeps_prefix_and_extracts_user_id(self):
        """Test that idt token with Bearer keeps prefix and extracts user ID"""
        token = "Bearer idt:TKN-1234-5678:secret"
        client = APIClient(base_url="https://api.example.com", token=token)

        # Should keep Bearer prefix
        assert client.token == token

        # Should have user_id extracted
        assert client.user_id == "TKN-1234-5678"

    def test_real_world_token_example(self):
        """Test with a real-world token format"""
        token = "idt:TKN-0291-1452:4l6Fq7jrGSfZVjDYHabJkxTuv4nynuj5f8qVTbbHJS5rFXpetnvRYfvwiaRjGzrF"
        client = APIClient(base_url="https://api.s1.show/public", token=token)

        # Verify all features work together
        assert client.base_url == "https://api.s1.show"  # URL normalized
        assert client.token.startswith("Bearer ")  # Bearer added
        assert client.user_id == "TKN-0291-1452"  # User ID extracted

        # Verify headers are correct
        headers = client._get_headers()
        assert headers["Authorization"] == f"Bearer {token}"
