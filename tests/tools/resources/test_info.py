import pytest

from mpt_mcp.tools.resources.info import describe_resource_info


@pytest.fixture
def resource_info_factory(spec_factory, products_registry):
    def factory(resource):
        return describe_resource_info(
            resource, spec_factory(registry=products_registry)
        ).model_dump()

    return factory


def test_resource_info_notes_omitted_fields(resource_info_factory):
    result = resource_info_factory("catalog.products")

    assert "$meta.omitted" in result["omitted_fields_note"]
    assert "select=+field" in result["omitted_fields_note"]


def test_resource_info_select_documents_omitted(resource_info_factory):
    result = resource_info_factory("catalog.products")

    select_doc = result["common_parameters"]["select"]
    assert "select=-*,+id,+name" in select_doc
    assert "$meta.omitted" in select_doc


def test_resource_info_shows_enum_fields(resource_info_factory):
    result = resource_info_factory("catalog.products")

    assert result["enum_fields"] == {"status": ["Draft", "Published"]}
    assert result["filtering_tips"] == "Filter by status using RQL: eq(status,<value>)"
    assert result["example_queries"] == [
        "marketplace_query(resource='catalog.products', limit=10)",
        "marketplace_query(resource='catalog.products', rql='eq(status,Draft)', limit=10)",
    ]


def test_resource_info_shows_path_parameters(resource_info_factory):
    result = resource_info_factory("catalog.products.by_id")

    assert result["path_parameters"] == {
        "id": {"type": "string", "description": "Path parameter: id", "required": True}
    }
    assert result["path_params_required"] == "This resource requires path parameters: id=<value>"
    assert result["example_queries"][-1] == (
        "marketplace_query(resource='catalog.products.by_id', path_params={'id': '<id_value>'}, "
        "select='-*,+id,+name')"
    )


def test_resource_info_without_related_resources(resource_info_factory):
    result = resource_info_factory("catalog.items")

    assert "related_resources" not in result
    assert "enum_fields" not in result
    assert "path_parameters" not in result
