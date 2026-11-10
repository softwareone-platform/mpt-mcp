import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (directory containing mpt_mcp/), so env is found regardless of cwd.
# When Cursor or another tool starts the MCP, cwd may not be the repo root.
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
load_dotenv(_env_file)
if not _env_file.exists():
    # Fallback: try cwd (e.g. when run as "python -m mpt_mcp.runtime.runner" from repo root)
    load_dotenv()


@dataclass
class Config:
    """Application configuration."""

    # API Configuration
    marketplace_api_base_url: str = os.getenv(
        "MARKETPLACE_API_BASE_URL", "https://api.platform.softwareone.com"
    )
    marketplace_api_token: str = os.getenv("MARKETPLACE_API_TOKEN", "")

    # Server Configuration
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # The HTTP server is multi-tenant: clients send their credentials in the X-MPT-* headers
    # Endpoint used when a client does not send the X-MPT-Endpoint header
    http_default_base_url: str = os.getenv(
        "HTTP_DEFAULT_BASE_URL", "https://api.platform.softwareone.com"
    )

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
    # JWT exp leeway in seconds for clock skew (default 120). Token accepted if exp >= now - leeway.
    jwt_exp_leeway_seconds: int = int(os.getenv("JWT_EXP_LEEWAY_SECONDS", "120"))

    # Analytics Database (Optional - for usage tracking)
    # Format: postgresql+asyncpg://user:password@host:port/database
    analytics_database_url: str = os.getenv("ANALYTICS_DATABASE_URL", "")

    def validate(self) -> list[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.marketplace_api_base_url:
            errors.append("MARKETPLACE_API_BASE_URL is not configured")

        if not self.marketplace_api_token:
            errors.append("MARKETPLACE_API_TOKEN is not configured")

        return errors


# Global config instance
config = Config()
