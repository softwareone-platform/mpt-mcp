# Dockerfile for SoftwareOne Marketplace MCP Server (HTTP Streamable Transport)
# This allows deployment to cloud platforms like Google Cloud Run

FROM python:3.14-slim

# Install uv from official image (reliable in CI; no install script)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies with uv (lockfile ensures reproducible builds)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# Copy Alembic configuration and migrations (for analytics)
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Create cache directory
RUN mkdir -p .cache

# Expose port (Cloud Run will set PORT env var)
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Start HTTP server
CMD ["python", "-m", "src.server"]

