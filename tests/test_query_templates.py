"""Tests for query templates module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.query_templates import get_query_templates


class TestQueryTemplatesStructure:
    """Test the structure and content of query templates."""

    def test_get_query_templates_returns_dict(self):
        """Test that get_query_templates returns a dictionary."""
        templates = get_query_templates()
        assert isinstance(templates, dict)

    def test_expected_categories_exist(self):
        """Test that all expected categories are present."""
        templates = get_query_templates()
        expected_categories = ["orders", "products", "agreements", "subscriptions", "accounts", "tips"]

        for category in expected_categories:
            assert category in templates, f"Missing category: {category}"

    def test_category_has_description_and_templates(self):
        """Test that each category (except tips) has description and templates."""
        templates = get_query_templates()
        categories_with_templates = ["orders", "products", "agreements", "subscriptions", "accounts"]

        for category in categories_with_templates:
            assert "description" in templates[category], f"{category} missing description"
            assert "templates" in templates[category], f"{category} missing templates"
            assert isinstance(templates[category]["templates"], list), f"{category} templates should be a list"
            assert len(templates[category]["templates"]) > 0, f"{category} should have at least one template"

    def test_template_has_required_fields(self):
        """Test that each template has required fields."""
        templates = get_query_templates()
        required_fields = ["name", "description", "query", "use_case"]
        categories_with_templates = ["orders", "products", "agreements", "subscriptions", "accounts"]

        for category in categories_with_templates:
            for i, template in enumerate(templates[category]["templates"]):
                for field in required_fields:
                    assert field in template, f"{category} template {i} missing field: {field}"
                    assert isinstance(template[field], str), f"{category} template {i} {field} should be string"
                    assert len(template[field]) > 0, f"{category} template {i} {field} should not be empty"

    def test_template_query_format(self):
        """Test that template queries follow expected format."""
        templates = get_query_templates()
        categories_with_templates = ["orders", "products", "agreements", "subscriptions", "accounts"]

        for category in categories_with_templates:
            for template in templates[category]["templates"]:
                query = template["query"]
                assert query.startswith("marketplace_query("), f"Query should start with marketplace_query(): {query}"
                assert "resource=" in query, f"Query should contain resource parameter: {query}"
                assert query.endswith(")"), f"Query should end with closing parenthesis: {query}"


class TestQueryTemplatesContent:
    """Test specific content of query templates."""

    def test_orders_category_content(self):
        """Test orders category has expected templates."""
        templates = get_query_templates()
        orders = templates["orders"]

        assert orders["description"] == "Common order queries"
        assert len(orders["templates"]) >= 5, "Orders should have at least 5 templates"

        template_names = [t["name"] for t in orders["templates"]]
        assert "Recent orders" in template_names
        assert "Orders by status" in template_names

    def test_products_category_content(self):
        """Test products category has expected templates."""
        templates = get_query_templates()
        products = templates["products"]

        assert products["description"] == "Common product queries"
        assert len(products["templates"]) >= 5, "Products should have at least 5 templates"

        template_names = [t["name"] for t in products["templates"]]
        assert "Published products" in template_names
        assert "Search products by name" in template_names

    def test_agreements_category_content(self):
        """Test agreements category has expected templates."""
        templates = get_query_templates()
        agreements = templates["agreements"]

        assert agreements["description"] == "Common agreement queries"
        assert len(agreements["templates"]) >= 3, "Agreements should have at least 3 templates"

        template_names = [t["name"] for t in agreements["templates"]]
        assert "Active agreements" in template_names

    def test_subscriptions_category_content(self):
        """Test subscriptions category has expected templates."""
        templates = get_query_templates()
        subscriptions = templates["subscriptions"]

        assert subscriptions["description"] == "Common subscription queries"
        assert len(subscriptions["templates"]) >= 3, "Subscriptions should have at least 3 templates"

        template_names = [t["name"] for t in subscriptions["templates"]]
        assert "Active subscriptions" in template_names

    def test_accounts_category_content(self):
        """Test accounts category has expected templates."""
        templates = get_query_templates()
        accounts = templates["accounts"]

        assert accounts["description"] == "Common account queries"
        assert len(accounts["templates"]) >= 3, "Accounts should have at least 3 templates"

        template_names = [t["name"] for t in accounts["templates"]]
        assert "Active buyers" in template_names


class TestQueryTemplatesTips:
    """Test the tips section of query templates."""

    def test_tips_section_exists(self):
        """Test that tips section exists."""
        templates = get_query_templates()
        assert "tips" in templates
        assert isinstance(templates["tips"], dict)

    def test_tips_has_how_to_use(self):
        """Test that tips has how_to_use section."""
        templates = get_query_templates()
        tips = templates["tips"]

        assert "how_to_use" in tips
        assert isinstance(tips["how_to_use"], list)
        assert len(tips["how_to_use"]) >= 3, "Should have at least 3 usage tips"

        for tip in tips["how_to_use"]:
            assert isinstance(tip, str)
            assert len(tip) > 0

    def test_tips_has_rql_basics(self):
        """Test that tips has rql_basics section."""
        templates = get_query_templates()
        tips = templates["tips"]

        assert "rql_basics" in tips
        assert isinstance(tips["rql_basics"], dict)

        expected_rql_operators = ["equality", "search", "comparison", "combine", "sorting"]
        for operator in expected_rql_operators:
            assert operator in tips["rql_basics"], f"Missing RQL operator: {operator}"
            assert isinstance(tips["rql_basics"][operator], str)
            assert len(tips["rql_basics"][operator]) > 0


class TestQueryTemplatesAvailableStatuses:
    """Test that templates with status filters include available_statuses."""

    def test_templates_with_status_have_available_values(self):
        """Test that templates filtering by status include available_statuses."""
        templates = get_query_templates()
        categories_with_templates = ["orders", "products", "agreements", "subscriptions", "accounts"]

        for category in categories_with_templates:
            for template in templates[category]["templates"]:
                query = template["query"]
                if "eq(status," in query or "status," in query:
                    if "status" in template["name"].lower() or "published" in template["name"].lower() or "active" in template["name"].lower():
                        assert "available_statuses" in template, f"{category} template '{template['name']}' should have available_statuses"
                        assert isinstance(template["available_statuses"], list)
                        assert len(template["available_statuses"]) > 0


class TestQueryTemplatesResourceReferences:
    """Test that query templates reference valid resources."""

    def test_orders_templates_reference_commerce_resources(self):
        """Test that order templates reference commerce resources."""
        templates = get_query_templates()

        for template in templates["orders"]["templates"]:
            query = template["query"]
            assert "commerce.orders" in query, f"Order template should reference commerce.orders: {query}"

    def test_products_templates_reference_catalog_resources(self):
        """Test that product templates reference catalog resources."""
        templates = get_query_templates()

        for template in templates["products"]["templates"]:
            query = template["query"]
            assert "catalog.products" in query, f"Product template should reference catalog.products: {query}"

    def test_agreements_templates_reference_commerce_resources(self):
        """Test that agreement templates reference commerce resources."""
        templates = get_query_templates()

        for template in templates["agreements"]["templates"]:
            query = template["query"]
            assert "commerce.agreements" in query, f"Agreement template should reference commerce.agreements: {query}"

    def test_subscriptions_templates_reference_commerce_resources(self):
        """Test that subscription templates reference commerce resources."""
        templates = get_query_templates()

        for template in templates["subscriptions"]["templates"]:
            query = template["query"]
            assert "commerce.subscriptions" in query, f"Subscription template should reference commerce.subscriptions: {query}"

    def test_accounts_templates_reference_accounts_resources(self):
        """Test that account templates reference accounts resources."""
        templates = get_query_templates()

        for template in templates["accounts"]["templates"]:
            query = template["query"]
            assert "accounts." in query, f"Account template should reference accounts resources: {query}"
