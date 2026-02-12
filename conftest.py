"""Pytest config: add project root to path, patch server tool/resource callables for tests."""

import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _patch_server_callables():
    from src import server

    async def _patch():
        mcp = server.mcp
        tools_list = await mcp.list_tools()
        resources_list = await mcp.list_resources()

        tools = {getattr(t, "name", str(i)): t for i, t in enumerate(tools_list or [])}
        resources = {getattr(r, "uri", str(i)): r for i, r in enumerate(resources_list or [])}

        for name, tool in tools.items():
            setattr(server, name, tool)
        for uri, resource in resources.items():
            name = getattr(resource, "name", None) or uri.replace("://", "_").replace("{", "").replace("}", "").replace("/", "_")
            if name and not hasattr(server, name):
                setattr(server, name, resource)

        for name in list(dir(server)):
            if name.startswith("_"):
                continue
            try:
                obj = getattr(server, name)
            except AttributeError:
                continue
            if hasattr(obj, "fn") and callable(getattr(obj, "fn")):
                setattr(server, name, obj.fn)

    asyncio.run(_patch())


_patch_server_callables()
