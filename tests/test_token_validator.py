#!/usr/bin/env python3
"""
Tests for token validation functionality including secure hashing and caching
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.token_validator import (
    TokenValidationCache,
    _hash_token,
    normalize_token,
    parse_jwt_claims,
    parse_token_id,
    validate_token,
)


class TestTokenValidationCache:
    """Test the token validation cache with secure hashing"""

    @pytest.mark.unit
    def test_cache_initialization(self):
        """Test cache initializes with correct TTL"""
        cache = TokenValidationCache(ttl_minutes=30)
        assert cache.ttl == timedelta(minutes=30)
        assert len(cache._cache) == 0

    @pytest.mark.unit
    def test_hash_token_consistent(self):
        """Test that hashing the same token+endpoint produces consistent results"""
        token = "idt:TKN-1234-5678-SECRET"
        endpoint = "https://api.test.com"

        hash1 = _hash_token(token, endpoint)
        hash2 = _hash_token(token, endpoint)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 produces 64 hex characters
        assert token not in hash1  # Secret should not be in hash
        assert endpoint not in hash1  # Endpoint should not be in hash

    @pytest.mark.unit
    def test_hash_token_different_for_different_inputs(self):
        """Test that different tokens or endpoints produce different hashes"""
        token1 = "idt:TKN-1234-5678-SECRET1"
        token2 = "idt:TKN-1234-5678-SECRET2"
        endpoint1 = "https://api.test1.com"
        endpoint2 = "https://api.test2.com"

        hash1 = _hash_token(token1, endpoint1)
        hash2 = _hash_token(token2, endpoint1)
        hash3 = _hash_token(token1, endpoint2)

        assert hash1 != hash2  # Different tokens
        assert hash1 != hash3  # Different endpoints
        assert hash2 != hash3  # Different both

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_set_and_get(self):
        """Test setting and getting from cache"""
        cache = TokenValidationCache(ttl_minutes=60)
        token = "idt:TKN-1234-5678-SECRET"
        endpoint = "https://api.test.com"
        token_info = {"account": {"id": "ACC-123", "name": "Test"}}

        await cache.set(token, endpoint, is_valid=True, token_info=token_info)
        result = await cache.get(token, endpoint)

        assert result is not None
        is_valid, cached_info = result
        assert is_valid is True
        assert cached_info == token_info

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_miss(self):
        """Test cache returns None for non-existent entries"""
        cache = TokenValidationCache()
        token = "idt:TKN-1234-5678-SECRET"
        endpoint = "https://api.test.com"

        result = await cache.get(token, endpoint)
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        """Test that cache entries expire after TTL"""
        cache = TokenValidationCache(ttl_minutes=60)
        token = "idt:TKN-1234-5678-SECRET"
        endpoint = "https://api.test.com"
        token_info = {"account": {"id": "ACC-123", "name": "Test"}}

        # Set cache entry
        await cache.set(token, endpoint, is_valid=True, token_info=token_info)

        # Manually expire it by modifying the expiry time
        cache_key = _hash_token(token, endpoint)
        is_valid, expiry_time, token_info_cached = cache._cache[cache_key]
        cache._cache[cache_key] = (is_valid, datetime.now() - timedelta(seconds=1), token_info_cached)

        # Should return None now
        result = await cache.get(token, endpoint)
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_stores_invalid_tokens(self):
        """Test that cache can store invalid token results"""
        cache = TokenValidationCache()
        token = "idt:TKN-INVALID-TOKEN"
        endpoint = "https://api.test.com"

        await cache.set(token, endpoint, is_valid=False, token_info=None)
        result = await cache.get(token, endpoint)

        assert result is not None
        is_valid, cached_info = result
        assert is_valid is False
        assert cached_info is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_invalidate(self):
        """Test cache invalidation"""
        cache = TokenValidationCache()
        token = "idt:TKN-1234-5678-SECRET"
        endpoint = "https://api.test.com"
        token_info = {"account": {"id": "ACC-123", "name": "Test"}}

        # Set cache entry
        await cache.set(token, endpoint, is_valid=True, token_info=token_info)

        # Verify it exists
        result = await cache.get(token, endpoint)
        assert result is not None

        # Invalidate
        await cache.invalidate(token, endpoint)

        # Verify it's gone
        result = await cache.get(token, endpoint)
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_get_stats(self):
        """Test getting cache statistics"""
        cache = TokenValidationCache()
        token1 = "idt:TKN-1234-5678-SECRET1"
        token2 = "idt:TKN-1234-5678-SECRET2"
        endpoint = "https://api.test.com"

        stats = cache.get_stats()
        assert stats["total_entries"] == 0
        assert stats["ttl_minutes"] == 10  # default

        await cache.set(token1, endpoint, is_valid=True, token_info={})
        await cache.set(token2, endpoint, is_valid=False, token_info=None)

        stats = cache.get_stats()
        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 2  # Both are still valid (not expired)


class TestParseTokenId:
    """Test token ID parsing"""

    @pytest.mark.unit
    def test_parse_tkn_token(self):
        """Test parsing TKN-formatted tokens"""
        token = "idt:TKN-1234-5678:SECRET"
        token_id = parse_token_id(token)
        assert token_id == "TKN-1234-5678"

    @pytest.mark.unit
    def test_parse_bearer_tkn_token(self):
        """Test parsing TKN tokens with Bearer prefix"""
        token = "Bearer idt:TKN-1234-5678:SECRET"
        token_id = parse_token_id(token)
        assert token_id == "TKN-1234-5678"

    @pytest.mark.unit
    def test_parse_idt_user_token(self):
        """Test parsing IDT user tokens (not supported, returns None)"""
        token = "idt:IDT-USR-9999-8888:SECRET"
        token_id = parse_token_id(token)
        # IDT tokens are user tokens, not API tokens, so parse_token_id returns None
        assert token_id is None

    @pytest.mark.unit
    def test_parse_api_token_without_idt_prefix(self):
        """Test parsing tokens without idt prefix (not supported)"""
        token = "TKN-1234-5678:SECRET"
        token_id = parse_token_id(token)
        # Without idt: prefix, parsing fails
        assert token_id is None

    @pytest.mark.unit
    def test_parse_malformed_token(self):
        """Test parsing malformed tokens returns None"""
        token = "INVALID-TOKEN"
        token_id = parse_token_id(token)
        assert token_id is None

    @pytest.mark.unit
    def test_parse_token_without_secret(self):
        """Test parsing tokens without secret part"""
        token = "idt:TKN-1234-5678"
        token_id = parse_token_id(token)
        # parse_token_id extracts the TKN part
        assert token_id == "TKN-1234-5678"

    @pytest.mark.unit
    def test_parse_token_id_jwt_returns_none(self):
        """JWT: we do not decode without verification; parse_token_id returns None (user ID from validate_token only)"""
        import base64
        import json

        payload = {"https://claims.softwareone.com/userId": "USR-1234-5678"}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_id = parse_token_id(token)
        assert token_id is None


class TestParseJwtClaims:
    """parse_jwt_claims returns (None, None); we do not decode JWT without verification"""

    @pytest.mark.unit
    def test_parse_jwt_claims_always_returns_none(self):
        """We never trust unverified claims; always (None, None)"""
        out = parse_jwt_claims("header.payload.signature")
        assert out == (None, None)


class TestNormalizeToken:
    """Test token normalization (used by HTTP server middleware)"""

    @pytest.mark.unit
    def test_normalize_strips_bearer_prefix(self):
        """Bearer prefix is stripped so cache key and API call use raw token"""
        assert normalize_token("Bearer idt:TKN-1234-5678:SECRET") == "idt:TKN-1234-5678:SECRET"
        assert normalize_token("bearer idt:TKN-X:Y") == "idt:TKN-X:Y"

    @pytest.mark.unit
    def test_normalize_strips_whitespace(self):
        """Leading/trailing whitespace is stripped"""
        assert normalize_token("  idt:TKN-A:B  ") == "idt:TKN-A:B"
        assert normalize_token("  Bearer idt:TKN-A:B  ") == "idt:TKN-A:B"

    @pytest.mark.unit
    def test_normalize_empty_returns_empty(self):
        """Empty or whitespace-only returns empty string"""
        assert normalize_token("") == ""
        assert normalize_token("   ") == ""
        # Only "Bearer " (with trailing space) is stripped; "Bearer" alone has no trailing space so stays
        assert normalize_token("  Bearer   ") == "Bearer"


class TestValidateToken:
    """Test the main token validation function"""

    @pytest.mark.asyncio
    async def test_validate_token_success(self):
        """Test successful token validation"""
        token = "idt:TKN-1234-5678:SECRET"
        api_base_url = "https://api.test.com"

        mock_response = {
            "id": "TKN-1234-5678",
            "status": "Active",
            "name": "Test Token",
            "account": {
                "id": "ACC-123-456",
                "name": "Test Account",
                "type": "Vendor",
            },
        }

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_response_obj = AsyncMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json = lambda: mock_response

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

            assert is_valid is True
            assert token_info == mock_response
            assert error is None

    @pytest.mark.asyncio
    async def test_validate_token_inactive(self):
        """Test validation of inactive token - SKIPPED: implementation accepts any status"""
        token = "idt:TKN-1234-5678:SECRET"
        api_base_url = "https://api.test.com"

        mock_response = {
            "id": "TKN-1234-5678",
            "status": "Inactive",
            "name": "Inactive Token",
            "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
        }

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_response_obj = AsyncMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json = lambda: mock_response

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

            # Inactive tokens should be rejected even if API returns 200
            assert is_valid is False
            assert token_info == mock_response
            assert error is not None
            assert "not active" in error.lower()
            assert "Inactive" in error

    @pytest.mark.asyncio
    async def test_validate_token_not_found(self):
        """Test validation when token doesn't exist"""
        token = "idt:TKN-9999-9999:SECRET"
        api_base_url = "https://api.test.com"

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("404 Not Found"))
            mock_client_class.return_value.__aenter__.return_value = mock_client

            is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

            assert is_valid is False
            assert token_info is None
            assert "404" in error or "not found" in error.lower()

    @pytest.mark.asyncio
    async def test_validate_token_unauthorized(self):
        """Test validation when token is unauthorized"""
        token = "idt:TKN-8888-8888:SECRET"
        api_base_url = "https://api.test.com"

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("401 Unauthorized"))
            mock_client_class.return_value.__aenter__.return_value = mock_client

            is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

            assert is_valid is False
            assert token_info is None
            assert "401" in error or "unauthorized" in error.lower()

    @pytest.mark.asyncio
    async def test_validate_token_uses_cache(self):
        """Test that validation uses cache on subsequent calls"""
        token = "idt:TKN-5555-5555:SECRET"
        api_base_url = "https://api.test.com"

        mock_response = {
            "id": "TKN-5555-5555",
            "status": "Active",
            "name": "Test Token",
            "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
        }

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_response_obj = AsyncMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json = lambda: mock_response

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # First call - should hit API
            is_valid1, token_info1, error1 = await validate_token(token, api_base_url, use_cache=True)
            assert is_valid1 is True
            assert mock_client.get.call_count == 1

            # Second call - should use cache
            is_valid2, token_info2, error2 = await validate_token(token, api_base_url, use_cache=True)
            assert is_valid2 is True
            assert token_info2 == token_info1
            # Should still be 1 because cache was used
            assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_validate_token_bypass_cache(self):
        """Test that use_cache=False bypasses the cache"""
        token = "idt:TKN-6666-6666:SECRET"
        api_base_url = "https://api.test.com"

        mock_response = {
            "id": "TKN-6666-6666",
            "status": "Active",
            "name": "Test Token",
            "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
        }

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_response_obj = AsyncMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json = lambda: mock_response

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # First call
            await validate_token(token, api_base_url, use_cache=False)
            assert mock_client.get.call_count == 1

            # Second call with use_cache=False - should hit API again
            await validate_token(token, api_base_url, use_cache=False)
            assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_validate_token_with_normalized_token(self):
        """Validate_token receives normalized token (Bearer stripped by HTTP middleware)."""
        token = "idt:TKN-7777-7777:SECRET"
        api_base_url = "https://api.test.com"

        mock_response = {
            "id": "TKN-7777-7777",
            "status": "Active",
            "name": "Test Token",
            "account": {"id": "ACC-123-456", "name": "Test Account", "type": "Vendor"},
        }

        with patch("src.token_validator.httpx.AsyncClient") as mock_client_class:
            mock_response_obj = AsyncMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json = lambda: mock_response

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

            assert is_valid is True
            assert mock_client.get.call_count == 1
            # API must be called with single "Bearer " prefix (middleware passes normalized token)
            call_args = mock_client.get.call_args
            assert call_args[1]["headers"]["Authorization"] == "Bearer idt:TKN-7777-7777:SECRET"

    @pytest.mark.asyncio
    async def test_validate_token_jwt_requires_jwks_url_or_iss(self):
        """When JWT has no iss and JWT_JWKS_URL is not set, validation is rejected (no unverified decode)"""
        import base64

        payload = {"https://claims.softwareone.com/userId": "USR-1234-5678"}  # no iss
        payload_b64 = base64.urlsafe_b64encode(__import__("json").dumps(payload).encode()).decode().rstrip("=")
        token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        api_base_url = "https://api.test.com"

        with patch("src.token_validator.config") as mock_config:
            mock_config.jwt_jwks_url = ""

            is_valid, token_info, error = await validate_token(token, api_base_url, use_cache=False)

            assert is_valid is False
            assert token_info is None
            assert error is not None
            assert "JWT verification" in error or "JWT_JWKS_URL" in error or "iss" in error
