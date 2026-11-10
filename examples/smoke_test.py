#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import ClientTransport, StdioTransport, StreamableHttpTransport

DEFAULT_URL = "http://localhost:8080/mcp"
DEFAULT_ENDPOINT = "https://api.platform.softwareone.com"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = frozenset((
    "marketplace_audit_fields",
    "marketplace_docs_index",
    "marketplace_docs_list",
    "marketplace_docs_read",
    "marketplace_query",
    "marketplace_resource_info",
    "marketplace_resource_schema",
    "marketplace_resources",
))
EXPECTED_PROMPTS = frozenset((
    "agreements_for_client",
    "orders_by_status",
    "orders_for_product",
    "products_by_vendor",
    "recent_orders",
    "search_buyers",
    "search_products",
    "subscriptions_due",
    "subscriptions_for_product",
))
WRITE_TOOLS = frozenset(("marketplace_refresh_cache",))
SELECTED_FIELDS = frozenset(("id", "name", "status"))
DOCS_UNAVAILABLE = "not available"
MAX_LIMIT = 100
ERROR_PREVIEW = 80
FAILURE_PREVIEW = 300


class CheckFailedError(Exception):
    """A use case returned something other than what it should."""


class CheckSkippedError(Exception):
    """A use case cannot run against this server, for example without GitBook."""


type Check = Callable[[], Awaitable[str]]


class SmokeTest:
    """Use cases of the MCP server, run one by one against a running server."""

    def __init__(self, client: Client[Any], *, http: bool, settings: argparse.Namespace) -> None:
        self.client = client
        self.http = http
        self.settings = settings
        self.product_id: str | None = None
        self.docs_uri: str | None = None

    def checks(self) -> list[tuple[str, Check]]:
        """
        List the use cases in the order they run: later ones reuse IDs found by earlier ones.

        Returns:
            Name and coroutine function of each use case
        """
        checks: list[tuple[str, Check]] = [
            ("tools are listed and annotated", self.check_tools),
            ("prompts are listed", self.check_prompts),
            ("prompt writes a marketplace_query call", self.check_prompt_text),
            ("api://openapi.json resource", self.check_openapi_resource),
            ("resources: search", self.check_resources_search),
            ("resources: category", self.check_resources_category),
            ("resources: category and search", self.check_resources_details),
            ("resource info", self.check_resource_info),
            ("resource schema", self.check_resource_schema),
            ("audit fields", self.check_audit_fields),
            ("query: first page", self.check_query_page),
            ("query: select only some fields", self.check_query_select),
            ("query: rql filter", self.check_query_filter),
            ("query: count with limit=0", self.check_query_count),
            ("query: next page with next_offset", self.check_query_pagination),
            ("query: order by audit field", self.check_query_audit_order),
            ("query: single item by id", self.check_query_by_id),
            ("error: missing path_params", self.check_missing_path_params),
            ("error: limit over the maximum", self.check_limit_too_large),
            ("error: unknown resource", self.check_unknown_resource),
            ("docs: index", self.check_docs_index),
            ("docs: list with search", self.check_docs_list),
            ("docs: read a page", self.check_docs_read),
        ]
        if self.http:
            checks.append(("error: invalid token", self.check_invalid_token))
        return checks

    async def check_tools(self) -> str:
        """
        Check that every tool is listed and that only the refresh tool writes.

        Returns:
            Number of tools
        """
        tools = await self.client.list_tools()
        names = {tool.name for tool in tools}
        missing = EXPECTED_TOOLS - names
        self._expect(not missing, f"missing tools: {sorted(missing)}")
        for tool in tools:
            read_only = bool(tool.annotations and tool.annotations.read_only_hint)
            self._expect(
                read_only != (tool.name in WRITE_TOOLS),
                f"{tool.name} has the wrong readOnlyHint",
            )
            self._expect(tool.output_schema is not None, f"{tool.name} has no output schema")
        return f"{len(tools)} tools"

    async def check_prompts(self) -> str:
        """
        Check that every prompt is listed.

        Returns:
            Number of prompts
        """
        names = {prompt.name for prompt in await self.client.list_prompts()}
        missing = EXPECTED_PROMPTS - names
        self._expect(not missing, f"missing prompts: {sorted(missing)}")
        return f"{len(names)} prompts"

    async def check_prompt_text(self) -> str:
        """
        Check that a prompt asks the model to run marketplace_query.

        Returns:
            Prompt checked
        """
        prompt = await self.client.get_prompt("search_products", {"name": "Microsoft"})
        text = json.dumps([message.model_dump(mode="json") for message in prompt.messages])
        self._expect("marketplace_query" in text, "search_products does not call the tool")
        return "search_products"

    async def check_openapi_resource(self) -> str:
        """
        Check that the OpenAPI spec of the caller's endpoint can be read, with its account.

        Returns:
            Endpoint, account and number of API paths
        """
        resource_contents = await self.client.read_resource("api://openapi.json")
        wrapper = json.loads(getattr(resource_contents[0], "text", "{}"))
        paths = (wrapper.get("spec") or {}).get("paths") or {}
        self._expect(bool(paths), "the spec has no paths")
        endpoint, account = wrapper.get("api_endpoint"), wrapper.get("authenticated_as")
        return f"{len(paths)} paths of {endpoint}, as {account}"

    async def check_resources_search(self) -> str:
        """
        Check that searching the resources finds commerce.orders.

        Returns:
            Number of resources found
        """
        found = await self._tool("marketplace_resources", search="order")
        names = self._resource_names(found)
        self._expect("commerce.orders" in names, "commerce.orders not found")
        return f"{found['total_resources']} resources"

    async def check_resources_category(self) -> str:
        """
        Check that a category lists its resources, shortened with a note when it is too long.

        Returns:
            Number of resources in the category, and whether they were shortened
        """
        found = await self._tool("marketplace_resources", category="catalog")
        entries = self._entries(found)
        self._expect(bool(entries), "the catalog category is empty")
        if found.get("note"):
            self._expect(all(entry.get("summary") for entry in entries), "an entry has no summary")
            return f"{len(entries)} resources, shortened with a note"
        self._expect(all(entry.get("path") for entry in entries), "an entry has no path")
        return f"{len(entries)} resources with their details"

    async def check_resources_details(self) -> str:
        """
        Check that a category narrowed with search lists its resources with their path.

        Returns:
            Number of resources found
        """
        found = await self._tool("marketplace_resources", category="catalog", search="listing")
        entries = self._entries(found)
        self._expect(bool(entries), "no catalog resource matches listing")
        self._expect(not found.get("note"), f"shortened: {found.get('note')}")
        self._expect(all(entry.get("path") for entry in entries), "an entry has no path")
        return f"{len(entries)} resources"

    async def check_resource_info(self) -> str:
        """
        Check that a resource is described with example queries.

        Returns:
            Number of example queries
        """
        examples = (await self._tool("marketplace_resource_info", resource="catalog.products"))[
            "example_queries"
        ]
        self._expect(bool(examples), "no example queries")
        return f"{len(examples)} examples"

    async def check_resource_schema(self) -> str:
        """
        Check that the response schema of a resource has its fields.

        Returns:
            Number of fields
        """
        schema = await self._tool("marketplace_resource_schema", resource="catalog.products")
        fields = schema.get("fields") or {}
        self._expect(bool(fields), "the schema has no fields")
        return f"{len(fields)} fields"

    async def check_audit_fields(self) -> str:
        """
        Check that orders have audit events.

        Returns:
            Audit events of commerce.orders
        """
        audit = await self._tool("marketplace_audit_fields", resource="commerce.orders")
        events = audit.get("events") or []
        self._expect("created" in events, f"no created event: {events}")
        return ", ".join(events)

    async def check_query_page(self) -> str:
        """
        Check the first page of products and keep a product ID for the later use cases.

        Returns:
            Items and total of the page
        """
        page = await self._tool("marketplace_query", resource="catalog.products", limit=1)
        products = page.get("data")
        self._expect(isinstance(products, list), "the page has no data list")
        pagination = page["$meta"]["pagination"]
        if products:
            self.product_id = products[0]["id"]
        return f"{pagination.get('returned')} of {pagination.get('total')} products"

    async def check_query_select(self) -> str:
        """
        Check that select=-* returns only the listed fields and the ones always kept.

        Returns:
            Fields of the first item
        """
        page = await self._tool(
            "marketplace_query",
            resource="catalog.products",
            select="-*,+id,+name",
            limit=3,
        )
        fields: set[str] = set()
        for product in page["data"]:
            fields |= set(product)
        extra = fields - SELECTED_FIELDS
        self._expect(not extra, f"fields not selected: {sorted(extra)}")
        return ", ".join(sorted(fields)) or "no products"

    async def check_query_filter(self) -> str:
        """
        Check an RQL filter on a text field.

        Returns:
            Items that match
        """
        page = await self._tool(
            "marketplace_query",
            resource="catalog.products",
            rql="ilike(name,*a*)",
            select="-*,+id,+name",
            limit=5,
        )
        names = [product["name"] for product in page["data"]]
        unmatched = [name for name in names if "a" not in name.lower()]
        self._expect(not unmatched, f"names that do not match: {unmatched}")
        return f"{len(page['data'])} products"

    async def check_query_count(self) -> str:
        """
        Check that limit=0 counts the matches without returning items.

        Returns:
            Total of products
        """
        page = await self._tool("marketplace_query", resource="catalog.products", limit=0)
        pagination = page["$meta"]["pagination"]
        self._expect(not page.get("data"), "limit=0 returned items")
        self._expect(pagination.get("total") is not None, "no total")
        self._expect(pagination.get("next_offset") is None, "limit=0 has a next_offset")
        return f"total {pagination['total']}"

    async def check_query_pagination(self) -> str:
        """
        Check that next_offset reads the next page.

        Returns:
            Offset of the second page
        """
        first = await self._tool(
            "marketplace_query", resource="catalog.products", select="-*,+id", limit=2
        )
        next_offset = first["$meta"]["pagination"].get("next_offset")
        if not first["$meta"]["pagination"].get("has_more"):
            raise CheckSkippedError("fewer than 3 products")
        second = await self._tool(
            "marketplace_query",
            resource="catalog.products",
            select="-*,+id",
            limit=2,
            offset=next_offset,
        )
        first_ids = {product["id"] for product in first["data"]}
        repeated = first_ids & {product["id"] for product in second["data"]}
        self._expect(not repeated, f"items repeated across pages: {sorted(repeated)}")
        return f"offset {next_offset}"

    async def check_query_audit_order(self) -> str:
        """
        Check that sorting by an audit field adds it to the items.

        Returns:
            Creation date of the newest order
        """
        page = await self._tool(
            "marketplace_query",
            resource="commerce.orders",
            order="-audit.created.at",
            select="-*,+id",
            limit=3,
        )
        if not page["data"]:
            raise CheckSkippedError("no orders visible to this token")
        dates = [order["audit"]["created"]["at"] for order in page["data"]]
        self._expect(dates == sorted(dates, reverse=True), f"not sorted: {dates}")
        return f"newest {dates[0]}"

    async def check_query_by_id(self) -> str:
        """
        Check that a by_id resource returns the item of the path parameter.

        Returns:
            Product ID read
        """
        if self.product_id is None:
            raise CheckSkippedError("no product found by the first page")
        product = await self._tool(
            "marketplace_query",
            resource="catalog.products.by_id",
            path_params={"id": self.product_id},
        )
        product_id = product.get("id")
        self._expect(product_id == self.product_id, f"got {product_id}")
        return self.product_id

    async def check_missing_path_params(self) -> str:
        """
        Check that a resource with path parameters fails without them.

        Returns:
            Start of the error message
        """
        return await self._tool_error(
            "requires path parameters", "marketplace_query", resource="catalog.products.by_id"
        )

    async def check_limit_too_large(self) -> str:
        """
        Check that a limit over the maximum fails validation.

        Returns:
            Start of the error message
        """
        return await self._tool_error(
            "less than or equal",
            "marketplace_query",
            resource="catalog.products",
            limit=MAX_LIMIT + 1,
        )

    async def check_unknown_resource(self) -> str:
        """
        Check that an unknown resource fails with a tool error.

        Returns:
            Start of the error message
        """
        return await self._tool_error(
            "Unknown resource", "marketplace_query", resource="catalog.does_not_exist"
        )

    async def check_docs_index(self) -> str:
        """
        Check the documentation table of contents, or skip without GitBook.

        Returns:
            Number of pages and sections
        """
        result = await self.client.call_tool("marketplace_docs_index", {}, raise_on_error=False)
        if result.is_error and DOCS_UNAVAILABLE in self._text(result):
            raise CheckSkippedError("GitBook is not configured on the server")
        index = self._structured(result, "marketplace_docs_index")
        self._expect(index["total_pages"] > 0, "the documentation has no pages")
        return f"{index['total_pages']} pages in {len(index['sections'])} sections"

    async def check_docs_list(self) -> str:
        """
        Check a documentation search and keep a page uri for the next use case.

        Returns:
            Number of pages found
        """
        result = await self.client.call_tool(
            "marketplace_docs_list", {"search": "order", "limit": 5}, raise_on_error=False
        )
        if result.is_error and DOCS_UNAVAILABLE in self._text(result):
            raise CheckSkippedError("GitBook is not configured on the server")
        pages = self._structured(result, "marketplace_docs_list")["resources"]
        self._expect(bool(pages), "no page matches order")
        self.docs_uri = pages[0]["uri"]
        return f"{len(pages)} pages"

    async def check_docs_read(self) -> str:
        """
        Read the page found by the documentation search.

        Returns:
            Page uri and length of its text
        """
        if self.docs_uri is None:
            raise CheckSkippedError("no page found by the documentation search")
        page = await self._tool("marketplace_docs_read", uri=self.docs_uri)
        self._expect(bool(page["text"]), "the page is empty")
        return f"{self.docs_uri} ({len(page['text'])} characters)"

    async def check_invalid_token(self) -> str:
        """
        Check that the HTTP server rejects a token that is not valid.

        Returns:
            How the call failed
        """
        transport = StreamableHttpTransport(
            self.settings.url,
            headers={
                "X-MPT-Authorization": "idt:TKN-0000-0000:not-a-valid-token",
                "X-MPT-Endpoint": self.settings.endpoint,
            },
        )
        try:
            async with Client(transport) as client:
                result = await client.call_tool(
                    "marketplace_query",
                    {"resource": "catalog.products", "limit": 1},
                    raise_on_error=False,
                )
        except Exception as error:
            return f"refused: {type(error).__name__}"
        self._expect(result.is_error, "the query worked with an invalid token")
        return self._text(result)[:ERROR_PREVIEW]

    async def _tool(self, name: str, **arguments: Any) -> dict[str, Any]:
        result = await self.client.call_tool(name, arguments, raise_on_error=False)
        if result.is_error:
            message = self._text(result)[:FAILURE_PREVIEW]
            raise CheckFailedError(f"{name} failed: {message}")
        return self._structured(result, name)

    async def _tool_error(self, expected: str, name: str, **arguments: Any) -> str:
        result = await self.client.call_tool(name, arguments, raise_on_error=False)
        self._expect(result.is_error, f"{name}({arguments}) did not fail")
        message = self._text(result)
        preview = message[:FAILURE_PREVIEW]
        self._expect(expected in message, f"unexpected error: {preview}")
        return message[:ERROR_PREVIEW]

    def _structured(self, result: CallToolResult, name: str) -> dict[str, Any]:
        self._expect(result.structured_content is not None, f"{name} has no structured content")
        return result.structured_content or {}

    def _text(self, result: CallToolResult) -> str:
        texts = [getattr(block, "text", "") for block in result.content]
        return " ".join(" ".join(texts).split())

    def _resource_names(self, found: dict[str, Any]) -> set[str]:
        return {entry["resource"] for entry in self._entries(found)}

    def _entries(self, found: dict[str, Any]) -> list[dict[str, Any]]:
        return [entry for group in found["categories"].values() for entry in group]

    def _expect(self, condition: object, message: str) -> None:
        if not condition:
            raise CheckFailedError(message)


class SmokeTestRunner:
    """Connect to the server, run every use case and print one line per use case."""

    def __init__(self, settings: argparse.Namespace) -> None:
        self.settings = settings

    async def run(self) -> int:
        """
        Run the use cases and print a summary.

        Returns:
            Exit code: 0 when no use case failed, 1 otherwise
        """
        transport = self._transport()
        failed = 0
        async with Client(transport) as client:
            smoke_test = SmokeTest(client, http=not self.settings.stdio, settings=self.settings)
            for name, check in smoke_test.checks():
                status, detail = await self._run_check(check)
                failed += status == "FAIL"
                sys.stdout.write(f"{status:<4}  {name:<40}  {detail}\n")
        summary = "FAILED" if failed else "OK"
        sys.stdout.write(f"\n{summary}: {failed} use cases failed\n")
        return 1 if failed else 0

    async def _run_check(self, check: Check) -> tuple[str, str]:
        try:
            detail = await check()
        except CheckSkippedError as skipped:
            return "SKIP", str(skipped)
        except Exception as error:
            return "FAIL", f"{type(error).__name__}: {error}"
        return "OK", detail

    def _transport(self) -> ClientTransport:
        if self.settings.stdio:
            return StdioTransport(
                command=sys.executable,
                args=["-m", "mpt_mcp.runtime.stdio"],
                env={
                    **os.environ,
                    "MARKETPLACE_API_TOKEN": self.settings.token,
                    "MARKETPLACE_API_BASE_URL": self.settings.endpoint,
                    "PYTHONPATH": str(REPOSITORY_ROOT),
                },
                cwd=str(REPOSITORY_ROOT),
            )
        return StreamableHttpTransport(
            self.settings.url,
            headers={
                "X-MPT-Authorization": self.settings.token,
                "X-MPT-Endpoint": self.settings.endpoint,
            },
        )


def parse_arguments() -> argparse.Namespace:
    """
    Read the server to test and the credentials from the command line and the environment.

    Returns:
        Settings of the run
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run the use cases of the MCP server against a running HTTP server, "
            "or against a stdio server it starts, and print the result of each one."
        ),
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"HTTP server, default {DEFAULT_URL}")
    parser.add_argument(
        "--stdio", action="store_true", help="start the stdio server instead of using --url"
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MPT_API_ENDPOINT", DEFAULT_ENDPOINT),
        help="Marketplace API endpoint, default MPT_API_ENDPOINT or production",
    )
    settings = parser.parse_args()
    settings.token = os.environ.get("MPT_API_TOKEN", "")
    if not settings.token:
        parser.error("set MPT_API_TOKEN to a Marketplace API token")
    return settings


if __name__ == "__main__":
    sys.exit(asyncio.run(SmokeTestRunner(parse_arguments()).run()))
