import pytest

from mpt_mcp.tools.responses import DocsPage, QueryResponse


def test_unset_optional_fields_are_left_out():
    response = QueryResponse.model_validate({"data": [{"id": "ORD-1234"}]})

    result = response.model_dump()

    assert result == {"data": [{"id": "ORD-1234"}]}


def test_aliases_and_undeclared_fields_are_kept():
    single_item = {"$meta": {"omitted": ["lines"]}, "id": "ORD-1234", "notes": None}
    response = QueryResponse.model_validate(single_item)

    result = response.model_dump()

    assert result == single_item


def test_required_fields_are_validated():
    with pytest.raises(ValueError, match="mimeType"):
        DocsPage.model_validate({"uri": "docs://readme", "name": "Readme", "description": ""})
