import datetime as dt
from typing import Annotated

from fastmcp.server.providers import LocalProvider
from pydantic import Field

ORDER_STATUSES = (
    "New, Draft, Querying, Processing, Quoted, Scheduled, Completed, Failed, Cancelling, Cancelled"
)
DUE_DAYS_DEFAULT = 30
marketplace_prompts = LocalProvider()


def query_request(
    *, resource: str, select: str, summary: str, rql: str = "", order: str = ""
) -> str:
    """
    Build the user message of a prompt: one marketplace_query call and how to present it.

    Args:
        resource: Resource to query, e.g. commerce.orders
        select: Fields to return, e.g. -*,+id,+status
        summary: How to present the items, e.g. as a table with their id and status
        rql: RQL filter
        order: Sort order

    Returns:
        Message that asks for the query and the summary
    """
    arguments = [f"resource={resource}"]
    if rql:
        arguments.append(f"rql={rql}")
    if order:
        arguments.append(f"order={order}")
    arguments.append(f"select={select}")
    call_arguments = ", ".join(arguments)
    return (
        f"Call marketplace_query with {call_arguments}. "
        f"Show the items {summary}, and say how many match in total "
        "($meta.pagination.total). If there are more, offer the next page."
    )


@marketplace_prompts.prompt(title="Recent orders")
def recent_orders() -> str:
    """List the most recently created Marketplace orders, in any status."""
    return query_request(
        resource="commerce.orders",
        order="-audit.created.at",
        select="-*,+id,+status,+product.name,+client.name",
        summary="as a table with their id, status, product, client and creation date",
    )


@marketplace_prompts.prompt(title="Orders in a status")
def orders_by_status(
    status: Annotated[str, Field(description=f"Order status: {ORDER_STATUSES}")],
) -> str:
    """List the Marketplace orders in one status, the last updated first."""
    return query_request(
        resource="commerce.orders",
        rql=f"eq(status,{status})",
        order="-audit.updated.at",
        select="-*,+id,+status,+product.name,+client.name",
        summary="as a table with their id, product, client and last update date",
    )


@marketplace_prompts.prompt(title="Orders of a product")
def orders_for_product(
    product_id: Annotated[str, Field(description="Product ID, e.g. PRD-1234-5678")],
) -> str:
    """List the most recent Marketplace orders of a product."""
    return query_request(
        resource="commerce.orders",
        rql=f"eq(product.id,{product_id})",
        order="-audit.created.at",
        select="-*,+id,+status,+client.name",
        summary="as a table with their id, status, client and creation date",
    )


@marketplace_prompts.prompt(title="Search products")
def search_products(
    name: Annotated[str, Field(description="Part of the product name, e.g. Adobe")],
) -> str:
    """Find Marketplace products by name."""
    return query_request(
        resource="catalog.products",
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
        resource="catalog.products",
        rql=f"eq(vendor.id,{vendor_id})",
        order="+name",
        select="-*,+id,+name,+status",
        summary="as a table with their id, name and status",
    )


@marketplace_prompts.prompt(title="Agreements of a client")
def agreements_for_client(
    client_id: Annotated[str, Field(description="Client account ID, e.g. ACC-1234-5678")],
) -> str:
    """List the Marketplace agreements of a client, newest first."""
    return query_request(
        resource="commerce.agreements",
        rql=f"eq(client.id,{client_id})",
        order="-audit.created.at",
        select="-*,+id,+name,+status,+product.name",
        summary="as a table with their id, name, status, product and creation date",
    )


@marketplace_prompts.prompt(title="Subscriptions of a product")
def subscriptions_for_product(
    product_id: Annotated[str, Field(description="Product ID, e.g. PRD-1234-5678")],
) -> str:
    """List the Marketplace subscriptions of a product."""
    return query_request(
        resource="commerce.subscriptions",
        rql=f"eq(product.id,{product_id})",
        order="-audit.created.at",
        select="-*,+id,+name,+status,+agreement.id,+commitmentDate",
        summary="as a table with their id, name, status, agreement and commitment date",
    )


@marketplace_prompts.prompt(title="Subscriptions due for renewal")
def subscriptions_due(
    days: Annotated[
        int, Field(description="How many days ahead to look, from today", ge=1)
    ] = DUE_DAYS_DEFAULT,
) -> str:
    """List the active Marketplace subscriptions whose commitment ends in the next days."""
    today = dt.datetime.now(dt.UTC).date()
    until = today + dt.timedelta(days=days)
    return query_request(
        resource="commerce.subscriptions",
        rql=(
            f"and(eq(status,Active),ge(commitmentDate,{today}T00:00:00.000Z),"
            f"lt(commitmentDate,{until}T00:00:00.000Z))"
        ),
        order="+commitmentDate",
        select="-*,+id,+name,+commitmentDate,+autoRenew,+product.name",
        summary="as a table with their id, name, product, commitment date and auto-renewal",
    )


@marketplace_prompts.prompt(title="Search buyers")
def search_buyers(
    name: Annotated[str, Field(description="Part of the buyer name, e.g. Contoso")],
) -> str:
    """Find Marketplace buyers by name."""
    return query_request(
        resource="accounts.buyers",
        rql=f"ilike(name,*{name}*)",
        order="+name",
        select="-*,+id,+name,+status",
        summary="as a table with their id, name and status",
    )
