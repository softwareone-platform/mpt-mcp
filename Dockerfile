# Dockerfile for SoftwareOne Marketplace MCP Server (HTTP Streamable Transport)
# This allows deployment to cloud platforms like Google Cloud Run

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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

