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
| `X-MPT-Endpoint` | no | Marketplace API endpoint; defaults to production |
| `X-MPT-Validate-Fresh` | no | `true` bypasses the 10-minute token validation cache |

Client configurations for Cursor, Claude Desktop and VS Code are in [`examples/`](../examples/README.md).

## Tools

| Tool | HTTP | stdio | Purpose |
|---|---|---|---|
| `marketplace_query` | yes | yes | Query a Marketplace API resource with RQL, `select`, `order` and pagination |
| `marketplace_resources` | yes | yes | List the queryable resources, grouped by category |
| `marketplace_resource_info` | yes | yes | Describe a resource: filterable fields, enum values, path parameters, examples |
| `marketplace_resource_schema` | yes | yes | Return the full response schema of a resource |
| `marketplace_audit_fields` | yes | yes | List the audit events (`created`, `updated`, `failed`…) of each resource |
| `marketplace_quick_queries` | yes | yes | Return ready-to-use query templates by category |
| `marketplace_docs_index` | yes | no | Return the documentation table of contents |
| `marketplace_docs_list` | yes | no | List documentation pages, filtered by section, subsection or search |
| `marketplace_docs_read` | yes | no | Read a documentation page by `docs://` URI |
| `marketplace_resources_info` | yes | no | Show the state of the documentation and token validation caches |
| `marketplace_cache_info` | no | `DEBUG=true` | Show the OpenAPI spec cache state |
| `marketplace_refresh_cache` | no | `DEBUG=true` | Reload the OpenAPI spec and the endpoint registry |

The documentation tools need GitBook to be configured on the server; otherwise they return a message saying it is not available.

The HTTP server also exposes two MCP resources: `api://openapi.json` (the OpenAPI spec of the caller's endpoint) and `docs://{path}` (documentation pages).

## Querying

Resources are named after their API path: `/public/v1/catalog/products` is `catalog.products`, and `/public/v1/catalog/items/{id}` is `catalog.items.by_id`. Use `marketplace_resources` to list them and `marketplace_resource_info` to see their fields before filtering.

```text
marketplace_query(resource="catalog.products", limit=10)
marketplace_query(resource="catalog.products", rql="eq(status,Published)", select="+id,+name")
marketplace_query(resource="commerce.orders", rql="ilike(product.name,*Microsoft*)", order="-audit.created.at")
marketplace_query(resource="catalog.products.by_id", path_params={"id": "PRD-1234-5678"})
```

Query behaviour:

- `limit` defaults to 10 and is capped at 100; use `offset` or `page` to paginate.
- `catalog.products` returns `+id,+name,+shortDescription` when no `select` is given.
- Filtering or sorting by an audit field (`audit.created.at`, `audit.failed.by`…) adds `audit` to `select`, which the API requires; if the API rejects it, the query is retried without it.
- `select` fields that are not in the resource schema are dropped when the schema is known.
- Resources with path parameters return an error with an example `path_params` when they are missing.

RQL syntax is described in the [Marketplace documentation](https://docs.platform.softwareone.com/developer-resources/rest-api/resource-query-language).
