# Configuration Examples

Example configurations for different deployment scenarios.

## VS Code Copilot

1. Generate an API Token in the [SoftwareOne Marketplace Platform](https://platform.softwareone.com)

2. Enable the MCP Gallery in VS Code settings: Set `chat.mcp.gallery.enabled` to `true`

3. Copy the configuration to your project:

```bash
mkdir -p .vscode && cp vscode_copilot_mcp.json .vscode/mcp.json
```

4. Open Copilot Chat and ask it to use the SoftwareOne Marketplace tool

**Note:** VS Code will prompt you for your API token on first use. Your token is securely stored and never exposed to the LLM.

---

## Claude Desktop (stdio mode)

### Local Python

```bash
cp claude_desktop_stdio.json ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

### Docker

```bash
cp claude_desktop_stdio_docker.json ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Note:** Update `MARKETPLACE_API_TOKEN` and `MARKETPLACE_API_BASE_URL` in the config file with your credentials.

---

## Cursor / Antigravity IDE (HTTP Streamable mode)

### HTTP Streamable (Recommended)

```bash
cp cursor_http.json ~/.cursor/mcp.json
```

Update the configuration with:
- Service URL (local: `http://localhost:8080/mcp` or your Cloud Run URL)
- `X-MPT-Authorization`: Your API token
- `X-MPT-Endpoint`: Your API endpoint (optional, defaults to production)

### stdio (Alternative for local development)

**Docker:**
```bash
cp cursor_stdio_docker.json ~/.cursor/mcp.json
```

**Local Python:**
```bash
cp cursor_stdio.json ~/.cursor/mcp.json
```

---

## Testing

### cURL Test

Test the HTTP server:
```bash
./curl_example.sh
```

### Python Client Example

Test API client directly:
```bash
python python_client_example.py
```

---

## Quick Reference

### stdio mode (Claude Desktop, local Cursor)
- ✅ Direct connection via stdin/stdout
- ✅ No server needed
- ✅ Credentials in config file
- ✅ Best for local development

### HTTP Streamable mode (Cursor, Antigravity IDE, Cloud)
- ✅ HTTP server (port 8080)
- ✅ Multi-tenant support
- ✅ Credentials via HTTP headers
- ✅ Deploy to cloud (Google Cloud Run)
- ✅ Works with remote IDEs

---

## Configuration Files

| File | Description | Use Case |
|------|-------------|----------|
| `vscode_copilot_mcp.json` | VS Code Copilot MCP config | VS Code with Copilot Chat |
| `claude_desktop_stdio.json` | Claude Desktop with local Python | Local development |
| `claude_desktop_stdio_docker.json` | Claude Desktop with Docker | Isolated environment |
| `cursor_http.json` | Cursor with HTTP server | Remote/cloud deployment |
| `cursor_stdio_docker.json` | Cursor with Docker stdio | Local development |
| `cursor_stdio.json` | Cursor with local Python stdio | Local development |
| `curl_example.sh` | HTTP server test script | Testing HTTP endpoint |
| `python_client_example.py` | Direct API client test | Testing API client |

---

## See Also

- [Main README](../README.md) - Quick start and deployment
- [GitHub Actions Setup](../docs/GITHUB_ACTIONS_SETUP.md) - CI/CD configuration
- [Custom Domain Setup](../docs/CUSTOM_DOMAIN.md) - Configure custom domain for Cloud Run
