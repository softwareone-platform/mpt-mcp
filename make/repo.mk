## Add repo-specific targets here. Do not modify the shared *.mk files.

ANALYTICS_DB_URL = postgresql+asyncpg://mcp_user:mcp_password@analytics-db:5432/mcp_analytics

run-analytics:  ## Run the HTTP server with the local analytics database (migrations run on startup)
	$(DC) --profile analytics up -d --wait analytics-db
	$(DC) run --rm --service-ports -e ANALYTICS_DATABASE_URL=$(ANALYTICS_DB_URL) app python -m mpt_mcp.runtime.runner

run-stdio:  ## Run the stdio server (requires MARKETPLACE_API_TOKEN in .env)
	$(DC) run --rm -i stdio
