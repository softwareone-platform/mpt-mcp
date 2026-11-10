import logging

logger = logging.getLogger(__name__)

JWT_PART_COUNT = 3


def is_jwt_token(token: str) -> bool:
    """
    Check if a token is a JWT (JSON Web Token).

    JWT format: header.payload.signature (3 parts separated by dots)

    Args:
        token: The token string to check

    Returns:
        True if token appears to be a JWT, False otherwise
    """
    if not token or not isinstance(token, str):
        return False

    parts = token.split(".")
    return len(parts) == JWT_PART_COUNT


def parse_token_id(token: str) -> str | None:
    """
    Parse token ID from a token string.

    Supports: API Token idt:TKN-XXXX-XXXX:secret_part (returns TKN-...).
    For JWT we do not decode without verification; TokenValidator verifies it with JWKS
    and extracts the user ID. This returns None for JWT.
    """
    if is_jwt_token(token):
        return None

    try:
        parts = token.split(":")
    except AttributeError as error:
        logger.warning("Failed to parse token ID: %s", error)
        return None

    if len(parts) >= 2 and parts[1].startswith("TKN-"):
        return parts[1]

    return None


def normalize_token(token: str) -> str:
    """
    Normalize token for consistent cache keys and API calls.

    - Strip leading/trailing whitespace.
    - If the value starts with "Bearer " (case-insensitive), strip that prefix
      so the stored value is the raw token (e.g. idt:TKN-xxx:secret).

    This ensures the same logical token produces one cache entry and avoids
    double-prefixing when calling the Marketplace API.
    """
    if not token or not isinstance(token, str):
        return ""

    normalized = token.strip()
    if normalized.upper().startswith("BEARER "):
        normalized = normalized[7:].strip()
    return normalized
