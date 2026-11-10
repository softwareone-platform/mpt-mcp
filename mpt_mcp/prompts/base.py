from fastmcp.server.providers import LocalProvider

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
