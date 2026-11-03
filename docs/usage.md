# Usage

This document describes how to connect to the server and use its tools. Running the servers locally is described in [local-development.md](local-development.md).

## Connecting

Use the HTTP server unless the MCP client can only launch a local process.

| Server | How to connect | Credentials |
|---|---|---|
| HTTP | `https://mcp.platform.softwareone.com/mcp` (streamable HTTP) | `X-MPT-Authorization` header on every request |
| stdio | The client runs `python -m mpt_mcp.server_stdio` or the Docker image | `MARKETPLACE_API_TOKEN` environment variable |

HTTP headers:

| Header | Required | Purpose |
|---|---|---|
| `X-MPT-Authorization` | yes | Marketplace API token (`idt:TKN-XXXX-XXXX:secret`) or user JWT |
| `X-MPT-Endpoint` | no | Marketplace API endpoint; defaults to production. Any path is ignored: `https://api.s1.show/public/v1` is read as `https://api.s1.show` |
| `X-MPT-Validate-Fresh` | no | `true` bypasses the 10-minute token validation cache |

Client configurations for Claude Code, Cursor, Claude Desktop and VS Code are in [`examples/`](../examples/README.md).

## Tools

The HTTP and stdio servers are one MCP server served over two transports, so they have the same tools, prompts and resources. The tools are:

| Tool | Purpose |
|---|---|
| `marketplace_query` | Query a Marketplace API resource with RQL, `select`, `order` and pagination |
| `marketplace_resources` | List the queryable resources by category, with their name and summary; `category` adds their path, description and filterable fields, and `search` filters by name or summary. A list longer than 25,000 characters keeps fewer fields and adds a `note` |
| `marketplace_resource_info` | Describe a resource: filterable fields, enum values, path parameters, examples |
| `marketplace_resource_schema` | Return the full response schema of a resource |
| `marketplace_audit_fields` | List the audit events (`created`, `updated`, `failed`…) of each resource |
| `marketplace_docs_index` | Return the documentation table of contents |
| `marketplace_docs_list` | List documentation pages, filtered by section, subsection or search |
| `marketplace_docs_read` | Read a documentation page by `docs://` URI; pages longer than 25,000 characters come in parts, read with `offset` |
| `marketplace_cache_info` | `DEBUG=true` only: show the OpenAPI spec cache state |
| `marketplace_refresh_cache` | `DEBUG=true` only: reload the OpenAPI spec and the endpoint registry |
| `marketplace_resources_info` | `DEBUG=true` only: show the state of the documentation and token validation caches |

The documentation tools need GitBook to be configured on the server; otherwise they fail with a message saying it is not available. A part of a long page sets `total_characters`, the `next_offset` to read the rest with and a `hint`; the last part has no `next_offset`.

Every tool publishes an output schema that describes the fields of its result, which is also sent as structured content. `marketplace_query` returns the API response: a page of items in `data` with `$meta` pagination, or the fields of a single item; resources that return a plain value are wrapped as `{"result": ...}`.

Every tool is read-only except `marketplace_refresh_cache`, and declares it with the MCP `readOnlyHint` annotation. Failures are MCP tool errors (`isError: true`): the text is the error message, followed by its hints as JSON when there are any. The server's MCP `instructions` describe the order to use the tools in.

The server also has prompts for common questions. A prompt is chosen by the user in the MCP client and writes the `marketplace_query` call for the model to run. In Claude Code it is the `/mcp__<name>__<prompt>` command, where `<name>` is the name given to the server in the MCP client configuration, for example `/mcp__mpt-local__recent_orders`:

| Prompt | Arguments | Question |
|---|---|---|
| `recent_orders` | | Latest orders, in any status |
| `orders_by_status` | `status` | Orders in one status, the last updated first |
| `orders_for_product` | `product_id` | Latest orders of a product |
| `search_products` | `name` | Products whose name contains the text |
| `products_by_vendor` | `vendor_id` | Products of a vendor |
| `agreements_for_client` | `client_id` | Agreements of a client, newest first |
| `subscriptions_for_product` | `product_id` | Subscriptions of a product |
| `subscriptions_due` | `days` (default 30) | Active subscriptions whose commitment ends in the next days |
| `search_buyers` | `name` | Buyers whose name contains the text |

The server also exposes two MCP resources: `api://openapi.json` (the OpenAPI spec of the caller's endpoint) and `docs://{path*}` (documentation pages, including nested paths such as `docs://help-and-support/contact-support`). A resource that cannot be read, because the caller has no valid token, the spec cannot be loaded or the page does not exist, fails with an MCP error instead of returning an error message as its content.

## Querying

Resources are named after their API path: `/public/v1/catalog/products` is `catalog.products`, and `/public/v1/catalog/items/{id}` is `catalog.items.by_id`. Use `marketplace_resources` to list them and `marketplace_resource_info` to see their fields before filtering.

```text
marketplace_query(resource="catalog.products", limit=10)
marketplace_query(resource="catalog.products", rql="eq(status,Published)", select="-*,+id,+name")
marketplace_query(resource="commerce.orders", rql="ilike(product.name,*Microsoft*)", order="-audit.created.at")
marketplace_query(resource="catalog.products.by_id", path_params={"id": "PRD-1234-5678"})
```

Query behaviour:

- `limit` defaults to 10 and is capped at 100; use `offset` to paginate. When the API gives the total, `$meta.pagination` adds `has_more` and the `next_offset` of the next page, which also continues a page cut to fit the result size. `$meta.pagination.returned` gives the items of the page. Resources that return a single item (`*.by_id`) take no `limit` or `offset`.
- A page longer than 25,000 characters is cut to the items that fit, so it does not fill the model's context or go over the tool result limit of clients that have one. `$meta.truncated` gives the items the API returned and a `suggested_limit` that fits with the same `select`, to fetch the next pages in parallel; `$meta.pagination.next_offset` continues the cut page. A page whose first item alone is longer fails and asks for a narrower `select`.
- Each item comes with the resource's default fields. `select` starting with `-*` returns only the listed fields (`-*,+id,+product.name`); without it, `+field` adds a field omitted by default (listed in `$meta.omitted`) and `-field` removes one. `id`, `status` and `name` are always kept when the resource has them.
- `catalog.products` returns only `id`, `status`, `name` and `shortDescription` when no `select` is given.
- Filtering or sorting by an audit field (`audit.created.at`, `audit.failed.by`…) adds that field to `select` (`+audit.created.at`), so the result shows the values it was sorted or filtered by. If the API answers 400 Bad Request, the query is sent again with the original `select`.
- `select` fields that are not in the resource schema are dropped when the schema is known.
- Resources with path parameters fail with an example `path_params` when they are missing.

RQL syntax is described in the [Marketplace documentation](https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language).
