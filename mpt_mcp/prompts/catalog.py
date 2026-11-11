from typing import Annotated

from pydantic import Field

from mpt_mcp.prompts.base import marketplace_prompts, query_request

PRODUCTS_RESOURCE = "catalog.products"


@marketplace_prompts.prompt(title="Search products")
def search_products(
    name: Annotated[str, Field(description="Part of the product name, e.g. Adobe")],
) -> str:
    """Find Marketplace products by name."""
    return query_request(
        resource=PRODUCTS_RESOURCE,
        rql=f"ilike(name,*{name}*)",
        order="+name",
        select="-*,+id,+name,+status,+vendor.id,+vendor.name",
        summary="as a table with their id, name, status and vendor",
    )


@marketplace_prompts.prompt(title="Products of a vendor")
def products_by_vendor(
    vendor_id: Annotated[str, Field(description="Vendor account ID, e.g. ACC-1234-5678")],
) -> str:
    """List the Marketplace products of a vendor."""
    return query_request(
        resource=PRODUCTS_RESOURCE,
        rql=f"eq(vendor.id,{vendor_id})",
        order="+name",
        select="-*,+id,+name,+status",
        summary="as a table with their id, name and status",
    )
