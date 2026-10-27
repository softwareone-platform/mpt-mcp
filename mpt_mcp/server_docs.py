import os

from .config import config
from .documentation_cache import DocumentationCache
from .gitbook_client import GitBookClient
from .server_context import log

documentation_cache: DocumentationCache | None = None
_docs_cache_initialized: bool = False
_docs_cache_init_pid: int | None = None


async def initialize_documentation_cache():
    global documentation_cache, _docs_cache_initialized, _docs_cache_init_pid
    current_pid = os.getpid()
    # Re-init whenever we're in a different process (worker after fork/spawn, or first run). Ensures worker has its own cache.
    if _docs_cache_init_pid != current_pid:
        _docs_cache_initialized = False
        documentation_cache = None
        _docs_cache_init_pid = None
    if _docs_cache_initialized:
        return
    log("📖 Loading documentation cache...")
    if config.gitbook_api_key and config.gitbook_space_id:
        try:
            gitbook_client = GitBookClient(
                api_key=config.gitbook_api_key,
                space_id=config.gitbook_space_id,
                base_url=config.gitbook_api_base_url,
                max_concurrent_requests=config.gitbook_max_concurrent_requests,
            )
            if await gitbook_client.validate_credentials():
                documentation_cache = DocumentationCache(
                    gitbook_client=gitbook_client,
                    refresh_interval_hours=config.gitbook_cache_refresh_hours,
                    public_url=config.gitbook_public_url,
                )
                await documentation_cache.refresh()
                doc_resources = await documentation_cache.list_resources()
                log(f"📝 Documentation cache loaded ({len(doc_resources)} pages); served via docs://{{path}} template")
                log("✓ Documentation cache initialized")
                log("✅ DOCS CACHE READY — marketplace_docs_list and docs:// resources are available")
            else:
                log("⚠️  GitBook credentials invalid, documentation cache disabled")
                documentation_cache = DocumentationCache(gitbook_client=None)
        except Exception as e:
            log(f"⚠️  Failed to initialize documentation cache: {e}")
            documentation_cache = DocumentationCache(gitbook_client=None)
    else:
        has_key = bool(config.gitbook_api_key)
        has_space = bool(config.gitbook_space_id)
        log(f"ℹ️  GitBook not configured, documentation cache disabled (GITBOOK_API_KEY={'set' if has_key else 'missing'}, GITBOOK_SPACE_ID={'set' if has_space else 'missing'}).")
        documentation_cache = DocumentationCache(gitbook_client=None)
    _docs_cache_initialized = True
    _docs_cache_init_pid = os.getpid()
