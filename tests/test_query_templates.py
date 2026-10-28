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
STATUS_WORDS = ("status", "published", "active")
STATUS_TEMPLATES = [
    (category, template)
    for category, template in TEMPLATES
    if "status," in template["query"]
    and any(word in template["name"].lower() for word in STATUS_WORDS)
]


def test_get_query_templates_returns_dict():
    result = get_query_templates()

    assert isinstance(result, dict)


def test_expected_categories_exist():
    result = get_query_templates()

    assert set(result) >= {*RESOURCE_BY_CATEGORY, "tips"}


@pytest.mark.parametrize("category", RESOURCE_BY_CATEGORY)
def test_category_has_description_and_templates(category):
    result = get_query_templates()[category]

    assert result["description"]
    assert isinstance(result["templates"], list)
    assert result["templates"]


@pytest.mark.parametrize(("category", "template"), TEMPLATES)
@pytest.mark.parametrize("field", ["name", "description", "query", "use_case"])
def test_template_has_required_fields(category, template, field):
    result = template.get(field)

    assert isinstance(result, str)
    assert result


@pytest.mark.parametrize(("category", "template"), TEMPLATES)
def test_template_query_format(category, template):
    result = template["query"]

    assert result.startswith("marketplace_query(")
    assert "resource=" in result
    assert result.endswith(")")


def test_orders_category_content():
    templates = get_query_templates()

    result = templates["orders"]

    assert result["description"] == "Common order queries"
    assert len(result["templates"]) >= 5, "Orders should have at least 5 templates"
    template_names = [template["name"] for template in result["templates"]]
    assert "Recent orders" in template_names
    assert "Orders by status" in template_names


def test_products_category_content():
    templates = get_query_templates()

    result = templates["products"]

    assert result["description"] == "Common product queries"
    assert len(result["templates"]) >= 5, "Products should have at least 5 templates"
    template_names = [template["name"] for template in result["templates"]]
    assert "Published products" in template_names
    assert "Search products by name" in template_names


def test_agreements_category_content():
    templates = get_query_templates()

    result = templates["agreements"]

    assert result["description"] == "Common agreement queries"
    assert len(result["templates"]) >= 3, "Agreements should have at least 3 templates"
    template_names = [template["name"] for template in result["templates"]]
    assert "Active agreements" in template_names


def test_subscriptions_category_content():
    templates = get_query_templates()

    result = templates["subscriptions"]

    assert result["description"] == "Common subscription queries"
    assert len(result["templates"]) >= 3, "Subscriptions should have at least 3 templates"
    template_names = [template["name"] for template in result["templates"]]
    assert "Active subscriptions" in template_names


def test_accounts_category_content():
    templates = get_query_templates()

    result = templates["accounts"]

    assert result["description"] == "Common account queries"
    assert len(result["templates"]) >= 3, "Accounts should have at least 3 templates"
    template_names = [template["name"] for template in result["templates"]]
    assert "Active buyers" in template_names


def test_tips_section_exists():
    result = get_query_templates()

    assert "tips" in result
    assert isinstance(result["tips"], dict)


def test_tips_has_how_to_use():
    templates = get_query_templates()

    result = templates["tips"]

    assert "how_to_use" in result
    assert isinstance(result["how_to_use"], list)
    assert len(result["how_to_use"]) >= 3, "Should have at least 3 usage tips"
    for tip in result["how_to_use"]:
        assert isinstance(tip, str)
        assert len(tip) > 0


def test_tips_has_rql_basics():
    templates = get_query_templates()

    result = templates["tips"]

    assert "rql_basics" in result
    assert isinstance(result["rql_basics"], dict)
    expected_rql_operators = ["equality", "search", "comparison", "combine", "sorting"]
    for operator in expected_rql_operators:
        assert operator in result["rql_basics"], f"Missing RQL operator: {operator}"
        assert isinstance(result["rql_basics"][operator], str)
        assert len(result["rql_basics"][operator]) > 0


@pytest.mark.parametrize(("category", "template"), STATUS_TEMPLATES)
def test_status_templates_have_available_values(category, template):
    result = template.get("available_statuses")

    assert isinstance(result, list)
    assert result


@pytest.mark.parametrize(("category", "template"), TEMPLATES)
def test_templates_reference_category_resource(category, template):
    result = template["query"]

    assert RESOURCE_BY_CATEGORY[category] in result
