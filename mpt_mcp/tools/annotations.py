from mcp_types import ToolAnnotations

# Every tool only reads: they differ in whether they reach the Marketplace API or GitBook
READ_ONLY_LOCAL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
READ_ONLY_REMOTE = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# Refreshing rewrites the server's spec cache: it changes state, but repeating it is harmless
REFRESHES_CACHE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
