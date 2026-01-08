#!/usr/bin/env python3
"""
Example: Using the SSE Multi-Tenant MCP Server from Python

This example shows how to connect to the SSE server and provide
your own API credentials.
"""

import httpx
import json

# Configuration
MCP_SERVER_URL = "http://localhost:8000/sse"
YOUR_API_TOKEN = "your_api_token_here"
YOUR_API_ENDPOINT = "https://api.platform.softwareone.com"  # Optional


async def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """
    Call an MCP tool via SSE with custom credentials
    
    Args:
        tool_name: Name of the tool to call (e.g., 'marketplace_query')
        arguments: Tool arguments as a dictionary
        
    Returns:
        Tool result as a dictionary
    """
    headers = {
        "X-MPT-Authorization": YOUR_API_TOKEN,
        "X-MPT-Endpoint": YOUR_API_ENDPOINT,
        "Content-Type": "application/json",
    }
    
    # MCP JSON-RPC request format
    request_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            MCP_SERVER_URL,
            json=request_data,
            headers=headers,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()


async def main():
    """Example usage"""
    
    print("=" * 60)
    print("MCP SSE Multi-Tenant Client Example")
    print("=" * 60)
    print()
    
    # Example 1: Query products
    print("Example 1: Get product count")
    print("-" * 60)
    
    result = await call_mcp_tool(
        "marketplace_query",
        {
            "resource": "catalog.products",
            "limit": 1
        }
    )
    
    print(json.dumps(result, indent=2))
    print()
    
    # Example 2: Search for Microsoft products
    print("Example 2: Search for Microsoft products")
    print("-" * 60)
    
    result = await call_mcp_tool(
        "marketplace_query",
        {
            "resource": "catalog.products",
            "rql": "ilike(name,*Microsoft*)",
            "limit": 5,
            "select": "+id,+name,+vendor"
        }
    )
    
    print(json.dumps(result, indent=2))
    print()
    
    # Example 3: List available resources
    print("Example 3: List available resources")
    print("-" * 60)
    
    result = await call_mcp_tool(
        "marketplace_resources",
        {}
    )
    
    print(json.dumps(result, indent=2)[:500] + "...")  # Truncate for display
    print()
    
    print("=" * 60)
    print("✅ Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

