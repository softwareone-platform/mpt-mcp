# SoftwareOne Marketplace MCP Server

Multi-tenant MCP server for the SoftwareOne Marketplace API with both stdio (local IDE integration) and HTTP streamable (remote access for Cursor, Antigravity IDE) support.

---

## 🚀 Quick Start

### **Claude Desktop (stdio mode)**

1. Copy config:
```bash
cp examples/claude_desktop_stdio_docker.json ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

2. Edit config with your credentials:
- `MARKETPLACE_API_TOKEN`: Your API token
- `MARKETPLACE_API_BASE_URL`: Your API endpoint

3. Restart Claude Desktop

### **Cursor / Antigravity IDE (HTTP Streamable mode)**

1. Start server:
```bash
docker compose up dev
```

2. Add to `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "softwareone-marketplace": {
      "url": "http://localhost:8080/mcp",
      "transport": "mcp",
      "headers": {
        "X-MPT-Authorization": "idt:TKN-XXXX-XXXX:your_token_here",
        "X-MPT-Endpoint": "https://api.platform.softwareone.com"
      }
    }
  }
}
```

3. Restart Cursor

---

## 🔄 CI/CD with GitHub Actions

Automated testing and deployment are configured via GitHub Actions:

- **PR Testing**: Automatically runs tests on every pull request
- **Auto-Deploy**: Deploys to Cloud Run when tests pass on main/master branch

---

## 🔧 Configuration

### **Environment Variables (stdio mode only)**
```bash
MARKETPLACE_API_TOKEN=your_token_here
MARKETPLACE_API_BASE_URL=https://api.platform.softwareone.com
```

### **HTTP Headers (HTTP Streamable mode)**
Provide these headers in your MCP client configuration:
```
X-MPT-Authorization: idt:TKN-XXXX-XXXX:your_token_here
X-MPT-Endpoint: https://api.platform.softwareone.com  # Optional, defaults to production
```

### **HTTP server (stateless and docs cache)**
The HTTP server always runs in stateless mode (no server-side sessions), avoiding 404 "Session not found" when load-balanced. The documentation cache is in memory per instance: populated at startup and long-lived for all requests in that process. `marketplace_docs_list` and `docs://` resources work with long-lived workers (default uvicorn/Cloud Run).

---

## 📚 API Query Examples

### **List products**
```
marketplace_query(resource="catalog.products", limit=10)
```

### **Filter with RQL**
```
marketplace_query(
    resource="catalog.products",
    rql="eq(status,Published)",
    limit=10
)
```

### **Get orders**
```
marketplace_query(resource="commerce.orders", limit=5)
```

---

## 🏗️ Development

This project uses **[uv](https://docs.astral.sh/uv/)** for dependency management. Install uv, then from the repo root:

```bash
uv sync                    # Create venv and install deps (incl. dev)
uv run pytest              # Run tests
uv run python -m mpt_mcp.server # Run HTTP server
uv run python -m mpt_mcp.server_stdio  # Run stdio server
```

To generate a `requirements.txt` for tools that still need it: `uv export --no-dev -o requirements.txt` (not stored in the repo).

### **Run tests (Docker)**
```bash
docker compose build test && docker compose run --rm test
```
This runs Ruff linter, Ruff formatter check, then pytest—the same checks as CI. After changing `pyproject.toml` or `uv.lock`, rebuild first: `docker compose build test`. To run only Ruff (lint + format check): `docker compose run --rm ruff`.

### **Local development (Docker)**
```bash
# HTTP server mode
docker compose up dev

# stdio mode
docker compose run --rm stdio
```

### **Analytics (Optional)**

Track usage statistics and performance metrics:

```bash
# 1. Start PostgreSQL database
docker compose --profile analytics up -d analytics-db

# 2. Run database migrations
docker compose --profile analytics run migrate

# 3. Configure server (add to .env or docker-compose.yml)
ANALYTICS_DATABASE_URL=postgresql+asyncpg://mcp_user:mcp_password@analytics-db:5432/mcp_analytics

# 4. Restart dev server
docker compose restart dev

# 5. Verify data collection
docker compose exec analytics-db psql -U mcp_user -d mcp_analytics -c "SELECT COUNT(*) FROM mcp_events;"
```

For more details, see:
- **Quick Start**: [docs/ANALYTICS_QUICKSTART.md](docs/ANALYTICS_QUICKSTART.md)
- **Full Documentation**: [docs/ANALYTICS_IMPLEMENTATION.md](docs/ANALYTICS_IMPLEMENTATION.md)

### **Code quality (SonarQube)**

Run SonarQube locally for security, maintainability, and coverage checks:

```bash
# 1. Start SonarQube
docker compose --profile sonar up -d sonar
# Open http://localhost:9000, login admin/admin, create project "mpt-mcp", generate a token

# 2. Generate coverage (optional)
uv run pytest --cov=mpt_mcp --cov-report=xml

# 3. Run scanner (set SONAR_TOKEN from SonarQube UI)
SONAR_TOKEN=your_token docker compose --profile sonar run --rm sonar-scanner
```

See **[docs/sonar.md](docs/sonar.md)** for full steps.

---

## 📦 Project Structure

```
mpt-mcp/
├── mpt_mcp/
│   ├── server.py              # HTTP server (Cursor, Antigravity, cloud)
│   ├── server_stdio.py        # stdio server (Claude Desktop)
│   ├── api_client.py          # Marketplace API client
│   ├── config.py              # Configuration
│   └── ...
├── examples/                  # Config examples
├── tests/                     # Test suite
├── docker-compose.yml         # Docker services
├── Dockerfile                 # Container image
├── pyproject.toml             # Project & dependencies (uv)
└── uv.lock                    # Locked dependency set
```

For stack, multi-tenancy, and guardrails, see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## 🔍 Troubleshooting

### **Cloud Run deployment fails**
- Check logs: `gcloud run services logs read mpt-mcp --region europe-west4`
- Verify health check: `curl https://mpt-mcp-XXXXX.run.app/health`

### **Cursor can't connect**
- Ensure server is running: `docker ps`
- Check logs: `docker compose logs dev`
- Verify port 8080 is accessible: `curl http://localhost:8080/health`

### **Claude Desktop errors**
- Check config path: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Verify Docker is running: `docker ps`
- Check Claude logs: `tail -f ~/Library/Logs/Claude/mcp*.log`

### **Agent-backend: "404 Not Found" for url 'http://host.docker.internal:8080/mcp'**
The error means the **MCP server** is not reachable at that URL (not the Marketplace API). The agent runs in Docker and calls the MCP at `http://host.docker.internal:8080/mcp`; something at that address is returning 404.

**Check:**
1. **MCP server is running and bound to 8080**  
   From the mpt-mcp repo: `docker compose up dev` (or ensure the container that serves MCP is up).  
   Then from the host: `curl -s http://localhost:8080/health` → should return `{"status":"healthy",...}`.  
   And: `curl -s -X POST http://localhost:8080/mcp -H "Content-Type: application/json" -d '{}'` → should not be 404 (may be 400/422 without proper MCP body).

2. **Port 8080 on the host**  
   `host.docker.internal:8080` from inside the agent container is the **host machine’s** port 8080. So either:
   - Run the MCP server on the host (e.g. `uv run python -m mpt_mcp.server`) so it listens on `localhost:8080`, or  
   - Run the MCP in Docker with `ports: ["8080:8080"]` (as in `docker-compose.yml` dev service) so the host’s 8080 is forwarded to the MCP container.

3. **Same Docker network (alternative)**  
   If the agent and mpt-mcp are in the same compose or shared network, point the agent at the MCP service by name instead of the host: e.g. `http://mpt-mcp-dev:8080/mcp` (and ensure the MCP container exposes 8080).

4. **Path**  
   The HTTP endpoint is **POST `/mcp`**. The server logs "Endpoint path: /mcp" at startup. If your client uses a different path (e.g. trailing slash or prefix), fix the agent’s MCP URL to end with `/mcp` with no trailing slash (unless the server is mounted elsewhere).

---

## 🔗 Links

- [MCP Documentation](https://modelcontextprotocol.io)
- [SoftwareOne Platform MCP Server Documentation](https://docs.platform.softwareone.com/developer-resources/mcp-server)
- [Google Cloud Run Docs](https://cloud.google.com/run/docs)
- [Cursor MCP Setup](https://docs.cursor.com/context/model-context-protocol)

---

## 📝 License

This project is licensed under the Apache License 2.0 - see the [LICENSE.md](LICENSE.md) file for details.

Copyright 2024-2026 SoftwareOne
