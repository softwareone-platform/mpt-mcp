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


@pytest.mark.parametrize(
    ("category", "description", "min_templates", "expected_names"),
    [
        ("orders", "Common order queries", 5, {"Recent orders", "Orders by status"}),
        (
            "products",
            "Common product queries",
            5,
            {"Published products", "Search products by name"},
        ),
        ("agreements", "Common agreement queries", 3, {"Active agreements"}),
        ("subscriptions", "Common subscription queries", 3, {"Active subscriptions"}),
        ("accounts", "Common account queries", 3, {"Active buyers"}),
    ],
)
def test_category_content(category, description, min_templates, expected_names):
    result = get_query_templates()[category]

    template_names = [template["name"] for template in result["templates"]]
    assert result["description"] == description
    assert len(template_names) >= min_templates
    assert expected_names <= set(template_names)


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
