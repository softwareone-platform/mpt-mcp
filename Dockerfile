# SoftwareOne Marketplace MCP Server
# Stages: dev (local development, tests and checks) and prod (Cloud Run image, built by default).

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS base

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN uv venv /opt/venv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

FROM base AS build

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

COPY . .

FROM build AS dev

RUN uv sync --frozen --no-cache --dev --no-install-project

CMD ["bash"]

FROM build AS prod

RUN mkdir -p .cache

# Expose port (Cloud Run will set PORT env var)
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

CMD ["python", "-m", "mpt_mcp.runtime.runner"]
