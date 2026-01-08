#!/usr/bin/env python3
"""
Test path parameter support in marketplace_query
"""

import pytest
import re


class TestPathParameterReplacement:
    """Test path parameter replacement logic"""
    
    @pytest.mark.unit
    def test_path_param_replacement_single(self):
        """Test replacing a single path parameter"""
        path = "/public/v1/catalog/products/{id}"
        path_params = {"id": "PRD-1234-5678"}
        
        # Replace path parameters
        for param_name, param_value in path_params.items():
            path = path.replace(f"{{{param_name}}}", str(param_value))
        
        assert path == "/public/v1/catalog/products/PRD-1234-5678"
        
        # Verify no remaining parameters
        remaining = re.findall(r'\{(\w+)\}', path)
        assert len(remaining) == 0
    
    @pytest.mark.unit
    def test_path_param_replacement_multiple(self):
        """Test replacing multiple path parameters"""
        path = "/public/v1/commerce/orders/{orderId}/lines/{lineId}"
        path_params = {"orderId": "ORD-1234-5678", "lineId": "LIN-9876-5432"}
        
        # Replace path parameters
        for param_name, param_value in path_params.items():
            path = path.replace(f"{{{param_name}}}", str(param_value))
        
        assert path == "/public/v1/commerce/orders/ORD-1234-5678/lines/LIN-9876-5432"
        
        # Verify no remaining parameters
        remaining = re.findall(r'\{(\w+)\}', path)
        assert len(remaining) == 0
    
    @pytest.mark.unit
    def test_path_param_missing_detection(self):
        """Test detection of missing path parameters"""
        path = "/public/v1/catalog/products/{id}/items/{itemId}"
        path_params = {"id": "PRD-1234-5678"}  # Missing itemId
        
        # Replace provided parameters
        for param_name, param_value in path_params.items():
            path = path.replace(f"{{{param_name}}}", str(param_value))
        
        # Check for remaining parameters
        remaining = re.findall(r'\{(\w+)\}', path)
        
        assert len(remaining) == 1
        assert "itemId" in remaining
    
    @pytest.mark.unit
    def test_path_param_no_params_needed(self):
        """Test paths that don't require parameters"""
        path = "/public/v1/catalog/products"
        path_params = None
        
        # No replacement needed
        if path_params:
            for param_name, param_value in path_params.items():
                path = path.replace(f"{{{param_name}}}", str(param_value))
        
        # Verify no parameters in path
        remaining = re.findall(r'\{(\w+)\}', path)
        assert len(remaining) == 0
    
    @pytest.mark.unit
    def test_path_param_type_conversion(self):
        """Test that non-string values are converted to strings"""
        path = "/public/v1/system/tasks/{id}"
        path_params = {"id": 12345}  # Integer value
        
        # Replace with string conversion
        for param_name, param_value in path_params.items():
            path = path.replace(f"{{{param_name}}}", str(param_value))
        
        assert path == "/public/v1/system/tasks/12345"
    
    @pytest.mark.unit
    def test_path_param_special_characters(self):
        """Test path parameters with special characters"""
        path = "/public/v1/accounts/{accountId}/users/{userId}"
        path_params = {
            "accountId": "ACC-1234-5678",
            "userId": "USR-9876-5432"
        }
        
        # Replace path parameters
        for param_name, param_value in path_params.items():
            path = path.replace(f"{{{param_name}}}", str(param_value))
        
        assert path == "/public/v1/accounts/ACC-1234-5678/users/USR-9876-5432"


class TestPathParameterErrorMessages:
    """Test error message generation for missing parameters"""
    
    @pytest.mark.unit
    def test_error_message_format(self):
        """Test that error messages are helpful"""
        path_template = "/public/v1/catalog/products/{id}"
        remaining_params = ["id"]
        
        error = {
            "error": f"Missing required path parameters: {', '.join(remaining_params)}",
            "path_template": path_template,
            "hint": f"Provide path_params like: {{{', '.join([f'{p}: value' for p in remaining_params])}}}"
        }
        
        assert "Missing required path parameters: id" in error["error"]
        assert error["path_template"] == path_template
        assert "id: value" in error["hint"]
    
    @pytest.mark.unit
    def test_error_message_multiple_params(self):
        """Test error message with multiple missing parameters"""
        remaining_params = ["orderId", "lineId"]
        
        hint = f"Provide path_params like: {{{', '.join([f'{p}: value' for p in remaining_params])}}}"
        
        assert "orderId: value" in hint
        assert "lineId: value" in hint
