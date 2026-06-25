# Project structure

- Rename the root package from `src` to `mptmcpsrv` or similar
- Move pytest configuration from `pytest.ini` to `pyproject.toml`
- Move conftest.py into tests directory
- Align ruff configuration with other python projects
- Pin major version only for dependencies
- Remove unused dependencies


# Dependencies

## Pin major version only

Currently, dependencies in `pyproject.toml` are specified using greater-or-equal (`>=`), which doesn't align with best practices. We should:

- Pin the **major version only** for libraries that follow semantic versioning (e.g., `requests>=2.31.0,<3`)
- Pin the **exact version** for other libraries
- Configure `uv` to automatically pin the major version when running `uv add`


## Migrate from python-jose to pyjwt

Even if `python-jose` is a good library, `pyjwt` is widely more used and backed by a larger community.
Furthermore, We are already using pyjwt in many other projects.


# Configuration

## Current approach and limitations

Currently, configuration is managed through dataclasses with manual extraction from environment variables using `python-dotenv`. This approach has several limitations:

- **No type validation**: Environment variables are strings; manual parsing is error-prone
- **Boilerplate code**: Repetitive extraction and conversion logic scattered throughout the codebase
- **Limited hierarchy**: Managing nested configuration structures requires custom handling
- **No environment-specific settings**: Supporting dev, staging, and production configs requires manual branching logic

## Migrate to Dynaconf

[Dynaconf](https://www.dynaconf.com/) provides a modern, flexible configuration management system:

- **Type-safe configuration**: Automatic type validation and conversion for all settings
- **Multiple sources**: Seamlessly merge configuration from environment variables, `.env` files, YAML, TOML, and JSON
- **Environment-aware**: Built-in support for environment-specific settings (dev, staging, production)
- **Validation**: Validate configuration on startup using Pydantic integration
- **Reduced boilerplate**: Single source of truth for all configuration with minimal code
- **Nested structures**: Native support for hierarchical configuration without custom parsing


# Marketplace API integration

## API call context

The `CredentialsMiddleware` is a low-level ASGI 3.0 application (middleware). It uses Starlette's `Request` object to parse the ASGI Scope to extract the context of the current call:

* Extracts the Marketplace API token from the request header `x-mpt-authorization`
* Extracts the Marketplace API endpoint to call from the header `x-mpt-endpoint`
* Extracts the current Agent session ID from the querystring parameter `session_id`.

It also logs the current call with extra meta information for analytics purposes.

The FastMCP framework provides two useful things to achive the same but in way more familiar to those who are familiar with modern python web framework, especially FastAPI:

* The [**Dependency Injection**](https://gofastmcp.com/servers/dependency-injection) system
* The [**Context**](https://gofastmcp.com/servers/context) class

```python
from dataclasses import dataclass

from fastmcp import FastMCP, Context
from fastmcp.dependencies import CurrentRequest, Depends
from starlette.requests import Request

mcp = FastMCP("Marketplace")

@dataclass
class CallContext:
    token: str
    endpoint: str
    session_id: str

    @property
    def user_id(self) -> str:
        if self.token and self.token.startswith("idt:") and self.token.count(":") >= 2:
            parts = self.token.split(":")
            if len(parts) >= 3 and parts[1].startswith("TKN-"):
                return parts[1]



async def get_call_context(request: Request = CurrentRequest()) -> CallContext:
    return CallContext(
        token=request.headers.get("x-mpt-authorization"),
        endpoint=request.headers.get("x-mpt-endpoint"),
        session_id=request.query_params.get("session_id"),
    )

async def authenticate(ctx: CallContext = Depends(get_call_context)) -> CallContext:
    if not ctx.token:
        raise ValueError(
            "Missing X-MPT-Authorization header. "
            "Please provide your API token in the X-MPT-Authorization header."
        )
    # apply token validation logic
    return ctx



@mcp.tool()
def my_tool(call_context: CallContext = Depends(authenticate)):
    pass
```


# Debugging Tools

Some tools are for debbugging purposes only. FastMCP provide a [simple and powerful way](https://gofastmcp.com/servers/visibility) to enable/disable tools.

Debugging tools must be enabled only for development through the server configuration.


# Analytics

The logic to capture analytics should be moved to an AnalyticsMiddleware. FastMCP middlewares are especially designed to intercept calls to tool and resource reads like in the following example:


```python
class AnalyticsMiddleware(Middleware):

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        result = await call_next(context)
        # save analytics data
        return result

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        result = await call_next(context)
        # save analytics data
        return result

```

# Caching

FastMCP is integrated with [py-key-value](https://strawgate.com/py-key-value) that can be used to cache the Marketplace documentation, the processed OpenAPI spec and the authentication context.

With the possibility of using different storage backends (Filesystem, Redis, etc), it is suitable for such caching.


# Tools

When designing MCP tools, it is essential to separate the tool response structure from its description. The agent does not rely on the tool description to understand what a response means — it relies on the JSON schema of the response, which travels alongside the data and describes the intent of each field. This is why descriptions must be embedded directly into the schema, on each field, rather than written in the tool description. Consider the following API response:

```json
{
  "success": true,
  "data": [
    { "id": "ORD-001", "status": "active", "total": 150.0 }
  ],
  "pagination": {
    "total": 243,
    "limit": 25,
    "offset": 0,
    "has_more": true,
    "next_offset": 25
  }
}
```

The agent can only correctly interpret this response — and know that it must call the tool again with offset: 25 — if the schema tells it so:

```json
{
  "properties": {
    "success": {
      "description": "Indicates whether the API call succeeded. If false, read the error field instead of data.",
      "type": "boolean"
    },
    "data": {
      "description": "The list of resources returned by the API for the current page.",
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "description": "Unique identifier of the resource. Use this value to reference this item in subsequent calls, for example to fetch its details or related resources.",
            "type": "string"
          },
          "status": {
            "description": "Current lifecycle status of the resource. Can be used as an RQL filter value with eq(status,<value>).",
            "type": "string"
          },
          "total": {
            "description": "Total monetary amount of the order in the account currency.",
            "type": "number"
          }
        }
      }
    },
    "pagination": {
      "description": "Metadata about the current page and the overall result set.",
      "properties": {
        "total": {
          "description": "Total number of items matching the query across all pages.",
          "type": "integer"
        },
        "limit": {
          "description": "Number of items returned in this page.",
          "type": "integer"
        },
        "offset": {
          "description": "Offset of the current page.",
          "type": "integer"
        },
        "has_more": {
          "description": "If true, more pages are available. Call the tool again with next_offset to retrieve the next page.",
          "type": "boolean"
        },
        "next_offset": {
          "description": "Pass this value as offset in the next call to retrieve the next page. Null if has_more is false.",
          "type": ["integer", "null"]
        }
      }
    }
  }
}
```
