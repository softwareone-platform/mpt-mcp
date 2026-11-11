from mpt_mcp.prompts.accounts import search_buyers


def test_search_buyers_searches_name():
    result = search_buyers("Contoso")

    assert "resource=accounts.buyers, rql=ilike(name,*Contoso*)" in result
