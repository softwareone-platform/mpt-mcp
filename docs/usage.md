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

Client configurations for Cursor, Claude Desktop and VS Code are in [`examples/`](../examples/README.md).

## Tools

Both servers serve the same tools:

| Tool | Purpose |
|---|---|
| `marketplace_query` | Query a Marketplace API resource with RQL, `select`, `order` and pagination |
| `marketplace_resources` | List the queryable resources, grouped by category |
| `marketplace_resource_info` | Describe a resource: filterable fields, enum values, path parameters, examples |
| `marketplace_resource_schema` | Return the full response schema of a resource |
| `marketplace_audit_fields` | List the audit events (`created`, `updated`, `failed`…) of each resource |
| `marketplace_quick_queries` | Return ready-to-use query templates by category |
| `marketplace_docs_index` | Return the documentation table of contents |
| `marketplace_docs_list` | List documentation pages, filtered by section, subsection or search |
| `marketplace_docs_read` | Read a documentation page by `docs://` URI |
| `marketplace_cache_info` | `DEBUG=true` only: show the OpenAPI spec cache state |
| `marketplace_refresh_cache` | `DEBUG=true` only: reload the OpenAPI spec and the endpoint registry |
| `marketplace_resources_info` | `DEBUG=true` only: show the state of the documentation and token validation caches |

The documentation tools need GitBook to be configured on the server; otherwise they return a message saying it is not available.

Both servers also expose two MCP resources: `api://openapi.json` (the OpenAPI spec of the caller's endpoint) and `docs://{path*}` (documentation pages, including nested paths such as `docs://help-and-support/contact-support`).

## Querying

Resources are named after their API path: `/public/v1/catalog/products` is `catalog.products`, and `/public/v1/catalog/items/{id}` is `catalog.items.by_id`. Use `marketplace_resources` to list them and `marketplace_resource_info` to see their fields before filtering.

```text
marketplace_query(resource="catalog.products", limit=10)
marketplace_query(resource="catalog.products", rql="eq(status,Published)", select="+id,+name")
marketplace_query(resource="commerce.orders", rql="ilike(product.name,*Microsoft*)", order="-audit.created.at")
marketplace_query(resource="catalog.products.by_id", path_params={"id": "PRD-1234-5678"})
```

Query behaviour:

- `limit` defaults to 10 and is capped at 100; use `offset` to paginate.
- `catalog.products` returns `+id,+name,+shortDescription` when no `select` is given.
- Filtering or sorting by an audit field (`audit.created.at`, `audit.failed.by`…) adds `audit` to `select`, which the API requires; if the API rejects it, the query is retried without it.
- `select` fields that are not in the resource schema are dropped when the schema is known.
- Resources with path parameters return an error with an example `path_params` when they are missing.

RQL syntax is described in the [Marketplace documentation](https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language).
