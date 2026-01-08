#!/usr/bin/env python3
"""
Test case-insensitive header detection for MPT headers
"""

import pytest
from starlette.datastructures import Headers


class TestMPTHeaders:
    """Test MPT header case-insensitive detection"""
    
    @pytest.mark.parametrize("header_name,value,description", [
        ("X-MPT-Authorization", "test_token_1", "Exact case"),
        ("mpt_authorization", "test_token_2", "Lowercase"),
        ("MPT_AUTHORIZATION", "test_token_3", "Uppercase"),
        ("Mpt_Authorization", "test_token_4", "Mixed case"),
        ("mPt_AuThOrIzAtIoN", "test_token_5", "Random case"),
    ])
    def test_authorization_header_case_insensitive(self, header_name, value, description):
        """Test that X-MPT-Authorization header works with any case"""
        headers = Headers({header_name: value})
        
        # Test retrieval with different cases
        retrieved = (
            headers.get("mpt_authorization") or 
            headers.get("X-MPT-Authorization") or
            headers.get("MPT_AUTHORIZATION")
        )
        
        assert retrieved == value, f"{description} failed: expected {value}, got {retrieved}"
    
    @pytest.mark.parametrize("header_name,value,description", [
        ("X-MPT-Endpoint", "https://api.test1.com", "Exact case"),
        ("mpt_endpoint", "https://api.test2.com", "Lowercase"),
        ("MPT_ENDPOINT", "https://api.test3.com", "Uppercase"),
        ("Mpt_Endpoint", "https://api.test4.com", "Mixed case"),
    ])
    def test_endpoint_header_case_insensitive(self, header_name, value, description):
        """Test that X-MPT-Endpoint header works with any case"""
        headers = Headers({header_name: value})
        
        retrieved = (
            headers.get("mpt_endpoint") or 
            headers.get("X-MPT-Endpoint") or
            headers.get("MPT_ENDPOINT")
        )
        
        assert retrieved == value, f"{description} failed: expected {value}, got {retrieved}"
    
    def test_headers_class_is_case_insensitive(self):
        """Test that Starlette Headers class is case-insensitive by default"""
        headers = Headers({"Content-Type": "application/json"})
        
        assert headers.get("content-type") == "application/json"
        assert headers.get("Content-Type") == "application/json"
        assert headers.get("CONTENT-TYPE") == "application/json"
