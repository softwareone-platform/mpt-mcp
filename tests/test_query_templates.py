import pytest

from mpt_mcp.query_templates import get_query_templates

RESOURCE_BY_CATEGORY = {
    "orders": "commerce.orders",
    "products": "catalog.products",
    "agreements": "commerce.agreements",
    "subscriptions": "commerce.subscriptions",
    "accounts": "accounts.",
}
TEMPLATES = [
    (category, template)
    for category in RESOURCE_BY_CATEGORY
    for template in get_query_templates()[category]["templates"]
]
STATUS_TEMPLATES = [
    (category, template)
    for category, template in TEMPLATES
    if "status," in template["query"]
    and any(word in template["name"].lower() for word in ("status", "published", "active"))
]


def test_get_query_templates_returns_dict():
    templates = get_query_templates()  # act

    assert isinstance(templates, dict)


def test_expected_categories_exist():
    templates = get_query_templates()

    expected_categories = [
        "orders",
        "products",
        "agreements",
        "subscriptions",
        "accounts",
        "tips",
    ]  # act

    for category in expected_categories:
        assert category in templates, f"Missing category: {category}"


def test_category_has_description_and_templates():
    templates = get_query_templates()

    categories_with_templates = [
        "orders",
        "products",
        "agreements",
        "subscriptions",
        "accounts",
    ]  # act

    for category in categories_with_templates:
        assert "description" in templates[category], f"{category} missing description"
        assert "templates" in templates[category], f"{category} missing templates"
        assert isinstance(templates[category]["templates"], list), (
            f"{category} templates should be a list"
        )
        assert len(templates[category]["templates"]) > 0, (
            f"{category} should have at least one template"
        )


def test_template_has_required_fields():
    templates = get_query_templates()
    required_fields = ["name", "description", "query", "use_case"]

    categories_with_templates = [
        "orders",
        "products",
        "agreements",
        "subscriptions",
        "accounts",
    ]  # act

    for category in categories_with_templates:
        for i, template in enumerate(templates[category]["templates"]):
            for field in required_fields:
                assert field in template, f"{category} template {i} missing field: {field}"
                assert isinstance(template[field], str), (
                    f"{category} template {i} {field} should be string"
                )
                assert len(template[field]) > 0, (
                    f"{category} template {i} {field} should not be empty"
                )


@pytest.mark.parametrize(("category", "template"), TEMPLATES)
def test_template_query_format(category, template):
    result = template["query"]

    assert result.startswith("marketplace_query(")
    assert "resource=" in result
    assert result.endswith(")")


def test_orders_category_content():
    templates = get_query_templates()

    orders = templates["orders"]  # act

    assert orders["description"] == "Common order queries"
    assert len(orders["templates"]) >= 5, "Orders should have at least 5 templates"
    template_names = [t["name"] for t in orders["templates"]]
    assert "Recent orders" in template_names
    assert "Orders by status" in template_names


def test_products_category_content():
    templates = get_query_templates()

    products = templates["products"]  # act

    assert products["description"] == "Common product queries"
    assert len(products["templates"]) >= 5, "Products should have at least 5 templates"
    template_names = [t["name"] for t in products["templates"]]
    assert "Published products" in template_names
    assert "Search products by name" in template_names


def test_agreements_category_content():
    templates = get_query_templates()

    agreements = templates["agreements"]  # act

    assert agreements["description"] == "Common agreement queries"
    assert len(agreements["templates"]) >= 3, "Agreements should have at least 3 templates"
    template_names = [t["name"] for t in agreements["templates"]]
    assert "Active agreements" in template_names


def test_subscriptions_category_content():
    templates = get_query_templates()

    subscriptions = templates["subscriptions"]  # act

    assert subscriptions["description"] == "Common subscription queries"
    assert len(subscriptions["templates"]) >= 3, "Subscriptions should have at least 3 templates"
    template_names = [t["name"] for t in subscriptions["templates"]]
    assert "Active subscriptions" in template_names


def test_accounts_category_content():
    templates = get_query_templates()

    accounts = templates["accounts"]  # act

    assert accounts["description"] == "Common account queries"
    assert len(accounts["templates"]) >= 3, "Accounts should have at least 3 templates"
    template_names = [t["name"] for t in accounts["templates"]]
    assert "Active buyers" in template_names


def test_tips_section_exists():
    templates = get_query_templates()  # act

    assert "tips" in templates
    assert isinstance(templates["tips"], dict)


def test_tips_has_how_to_use():
    templates = get_query_templates()

    tips = templates["tips"]  # act

    assert "how_to_use" in tips
    assert isinstance(tips["how_to_use"], list)
    assert len(tips["how_to_use"]) >= 3, "Should have at least 3 usage tips"
    for tip in tips["how_to_use"]:
        assert isinstance(tip, str)
        assert len(tip) > 0


def test_tips_has_rql_basics():
    templates = get_query_templates()

    tips = templates["tips"]  # act

    assert "rql_basics" in tips
    assert isinstance(tips["rql_basics"], dict)
    expected_rql_operators = ["equality", "search", "comparison", "combine", "sorting"]
    for operator in expected_rql_operators:
        assert operator in tips["rql_basics"], f"Missing RQL operator: {operator}"
        assert isinstance(tips["rql_basics"][operator], str)
        assert len(tips["rql_basics"][operator]) > 0


@pytest.mark.parametrize(("category", "template"), STATUS_TEMPLATES)
def test_templates_with_status_have_available_values(category, template):
    result = template.get("available_statuses")

    assert isinstance(result, list)
    assert result


@pytest.mark.parametrize(("category", "template"), TEMPLATES)
def test_templates_reference_their_category_resource(category, template):
    result = template["query"]

    assert RESOURCE_BY_CATEGORY[category] in result
