from typing import Annotated

from pydantic import Field

from mpt_mcp.prompts.base import marketplace_prompts, query_request

BUYERS_RESOURCE = "accounts.buyers"


@marketplace_prompts.prompt(title="Search buyers")
def search_buyers(
    name: Annotated[str, Field(description="Part of the buyer name, e.g. Contoso")],
) -> str:
    """Find Marketplace buyers by name."""
    return query_request(
        resource=BUYERS_RESOURCE,
        rql=f"ilike(name,*{name}*)",
        order="+name",
        select="-*,+id,+name,+status",
        summary="as a table with their id, name and status",
    )
