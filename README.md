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

### **Run tests**
```bash
docker compose run test
```
This runs Ruff linter, Ruff formatter check, then pytest—the same checks as CI. To run only Ruff (lint + format check): `docker compose run --rm ruff`.

### **Local development**
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

---

## 📦 Project Structure

```
mpt-mcp/
├── src/
│   ├── server.py              # HTTP server (Cursor, Antigravity, cloud)
│   ├── server_stdio.py        # stdio server (Claude Desktop)
│   ├── api_client.py          # Marketplace API client
│   ├── config.py              # Configuration
│   └── ...
├── examples/                  # Config examples
├── tests/                     # Test suite
├── docker-compose.yml         # Docker services
├── Dockerfile                 # Container image
└── requirements.txt           # Python dependencies
```

For stack, multi-tenancy, and guardrails, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

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
