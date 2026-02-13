import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (directory containing src/), so env is found regardless of cwd.
# When Cursor or another tool starts the MCP, cwd may not be the repo root.
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
load_dotenv(_env_file)
if not _env_file.exists():
    # Fallback: try cwd (e.g. when run as "python -m src.server" from repo root)
    load_dotenv()


def _parse_cors_origins() -> list[str]:
    """Parse CORS origins from environment variable"""
    origins = os.getenv("SSE_CORS_ORIGINS", "*")
    return [origin.strip() for origin in origins.split(",")]


@dataclass
class Config:
    """Application configuration"""

    # API Configuration
    marketplace_api_base_url: str = os.getenv("MARKETPLACE_API_BASE_URL", "https://api.platform.softwareone.com")
    marketplace_api_token: str = os.getenv("MARKETPLACE_API_TOKEN", "")
    openapi_spec_url: str = os.getenv("OPENAPI_SPEC_URL", "https://api.platform.softwareone.com/public/v1/openapi.json")

    # Server Configuration
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "30"))

    # SSE Server Configuration (for cloud deployment)
    sse_enabled: bool = os.getenv("SSE_ENABLED", "false").lower() == "true"
    sse_host: str = os.getenv("SSE_HOST", "0.0.0.0")
    # Railway/Render use PORT, fallback to SSE_PORT (default 8000)
    sse_port: int = int(os.getenv("PORT", os.getenv("SSE_PORT", "8000")))
    sse_cors_origins: list[str] = field(default_factory=_parse_cors_origins)

    # SSE is always multi-tenant - clients MUST provide credentials via MPT_Authorization header
    # Default base URL used when client doesn't specify MPT_Endpoint header
    sse_default_base_url: str = os.getenv("SSE_DEFAULT_BASE_URL", "https://api.platform.softwareone.com")

    # Tool Filtering (comma-separated path patterns)
    # Examples: "accounts,catalog" or "commerce/orders,commerce/subscriptions"
    tool_include_patterns: str = os.getenv("TOOL_INCLUDE_PATTERNS", "")
    tool_exclude_patterns: str = os.getenv("TOOL_EXCLUDE_PATTERNS", "")

    # GitBook Documentation Integration (Optional)
    gitbook_api_key: str = os.getenv("GITBOOK_API_KEY", "")
    gitbook_space_id: str = os.getenv("GITBOOK_SPACE_ID", "")
    gitbook_api_base_url: str = os.getenv("GITBOOK_API_BASE_URL", "https://api.gitbook.com/v1")
    gitbook_cache_refresh_hours: int = int(os.getenv("GITBOOK_CACHE_REFRESH_HOURS", "24"))
    # Max concurrent GitBook API requests (avoids 429 rate limits; default 2)
    gitbook_max_concurrent_requests: int = int(os.getenv("GITBOOK_MAX_CONCURRENT_REQUESTS", "2"))
    # Public URL where documentation is published (optional, for browser access)
    gitbook_public_url: str = os.getenv("GITBOOK_PUBLIC_URL", "")

    # JWT signature verification (optional but recommended for production)
    # When set, JWT tokens are verified using the issuer's JWKS before trusting claims.
    # Example: https://auth.softwareone.com/.well-known/jwks.json or your IdP's JWKS URL.
    jwt_jwks_url: str = os.getenv("JWT_JWKS_URL", "")

    # Analytics Database (Optional - for usage tracking)
    # Format: postgresql+asyncpg://user:password@host:port/database
    analytics_database_url: str = os.getenv("ANALYTICS_DATABASE_URL", "")
    analytics_enabled: bool = bool(os.getenv("ANALYTICS_DATABASE_URL", ""))

    def validate(self) -> list[str]:
        """
        Validate configuration

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.marketplace_api_base_url:
            errors.append("MARKETPLACE_API_BASE_URL is not configured")

        if not self.marketplace_api_token:
            errors.append("MARKETPLACE_API_TOKEN is not configured")

        if not self.openapi_spec_url:
            errors.append("OPENAPI_SPEC_URL is not configured")

        return errors


# Global config instance
config = Config()
