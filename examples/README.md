# Configuration Examples

MCP client configurations for the HTTP server and the stdio server. The servers, their headers and environment variables are described in [usage.md](../docs/usage.md) and [local-development.md](../docs/local-development.md).

Each example holds one server entry, `softwareone-marketplace`. Add that entry to the client's existing MCP configuration instead of copying the file over it: the client configuration files hold other servers and settings too.

Generate an API token in the [SoftwareOne Marketplace Platform](https://platform.softwareone.com) and replace `your_api_token_here` with it. To use a local HTTP server, replace the URL with `http://localhost:8080/mcp` and start it with `make run`.

## Claude Code (HTTP)

Add the server with `claude mcp add`. Its default `local` scope stores the server and your token in your user configuration (`~/.claude.json`) for the current folder only, so no file in the folder holds the token:

```bash
claude mcp add --transport http softwareone-marketplace https://mcp.platform.softwareone.com/mcp --header "X-MPT-Authorization: your_api_token_here"
```

Use `-s user` to make it available in every folder, and `claude mcp get softwareone-marketplace` to check it.

To share the server with a team, save [`claude_code_http.json`](claude_code_http.json) as `.mcp.json` in the project, or add its entry to an existing one. It reads the token from the `MPT_API_TOKEN` environment variable, so the file holds no secret and can be committed; each person exports their own token before starting Claude Code. Claude Code asks to approve project servers the first time.

## VS Code Copilot (HTTP)

1. Enable the MCP Gallery in VS Code settings: set `chat.mcp.gallery.enabled` to `true`.
2. Add the server and the `mpt-token` input of [`vscode_copilot_mcp.json`](vscode_copilot_mcp.json) to `.vscode/mcp.json` in your project, creating the file if it does not exist.
3. Open Copilot Chat and ask it to use the SoftwareOne Marketplace tools.

VS Code prompts for the API token on first use and stores it securely; the token is never exposed to the LLM.

## Cursor / Antigravity IDE (HTTP)

Add the entry of [`cursor_http.json`](cursor_http.json) to `mcpServers` in `~/.cursor/mcp.json`:

- `X-MPT-Authorization`: your API token
- `X-MPT-Endpoint`: your API endpoint (optional, defaults to production)

## Claude Desktop and Cursor (stdio)

Claude Desktop only runs stdio servers: add the entry to `mcpServers` in Settings → Developer → Edit Config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS) and restart Claude Desktop. Cursor reads the same entries from `~/.cursor/mcp.json`.

| File | Runs the server with |
|---|---|
| [`claude_desktop_stdio.json`](claude_desktop_stdio.json), [`cursor_stdio.json`](cursor_stdio.json) | The repository virtual environment: run `uv sync` first |
| [`claude_desktop_stdio_docker.json`](claude_desktop_stdio_docker.json), [`cursor_stdio_docker.json`](cursor_stdio_docker.json) | Docker Compose (`stdio` service) |

Replace `/absolute/path/to/mpt-mcp` with the path of your checkout, and set `MARKETPLACE_API_TOKEN` and `MARKETPLACE_API_BASE_URL`. The Docker examples pass both variables to the container with `-e`; other variables, such as `GITBOOK_API_KEY` or `DEBUG`, are read from the repository `.env` file.

## Checking the Server

[`smoke_test.py`](smoke_test.py) runs the use cases of the server against a real Marketplace API, prints `OK`, `FAIL` or `SKIP` for each one and exits with 1 when one fails. It needs `uv sync`, the token in `MPT_API_TOKEN` and, when the token is not a production one, its endpoint in `MPT_API_ENDPOINT`: the server validates the token against that endpoint, so a token of another environment is reported as invalid.

To test the HTTP server, start it first in another terminal and wait for it to answer on `http://localhost:8080/health`:

```bash
make run
```

Then run the script from the repository root. `--url` tests another HTTP server:

```bash
MPT_API_TOKEN=your_api_token_here MPT_API_ENDPOINT=https://api.s1.show uv run python examples/smoke_test.py
```

With `--stdio` the script starts the stdio server itself, so no server has to be running:

```bash
MPT_API_TOKEN=your_api_token_here MPT_API_ENDPOINT=https://api.s1.show uv run python examples/smoke_test.py --stdio
```

[`chat_check_prompt.md`](chat_check_prompt.md) is a prompt to paste in a chat of an MCP client connected to the server: the model runs the same use cases with the tools and ends with a table of the results, which also shows whether the tool descriptions lead it to the right calls.

[`curl_example.sh`](curl_example.sh) calls `marketplace_query` and `marketplace_resources` on a running HTTP server with curl; set `YOUR_API_TOKEN` and `YOUR_API_ENDPOINT` in the script first. It needs `jq`.

```bash
./curl_example.sh
```
