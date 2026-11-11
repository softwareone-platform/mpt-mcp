#!/bin/bash

# Example: Calling the HTTP MCP server with curl
# The server is stateless, so each tools/call request works without an initialize call.
# Responses are server-sent events: the JSON-RPC message is on the "data:" line.

# Configuration
MCP_SERVER_URL="http://localhost:8080/mcp"
YOUR_API_TOKEN="your_api_token_here"
YOUR_API_ENDPOINT="https://api.platform.softwareone.com"

echo "============================================================"
echo "MCP HTTP Multi-Tenant - curl Examples"
echo "============================================================"
echo ""

# Example 1: Get product count
echo "Example 1: Get product count"
echo "------------------------------------------------------------"

curl -s -X POST "$MCP_SERVER_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-MPT-Authorization: $YOUR_API_TOKEN" \
  -H "X-MPT-Endpoint: $YOUR_API_ENDPOINT" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "marketplace_query",
      "arguments": {
        "resource": "catalog.products",
        "limit": 1
      }
    }
  }' | sed -n 's/^data: //p' | jq '.result.structuredContent'

echo ""
echo ""

# Example 2: Search for Microsoft products
echo "Example 2: Search for Microsoft products"
echo "------------------------------------------------------------"

curl -s -X POST "$MCP_SERVER_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-MPT-Authorization: $YOUR_API_TOKEN" \
  -H "X-MPT-Endpoint: $YOUR_API_ENDPOINT" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "marketplace_query",
      "arguments": {
        "resource": "catalog.products",
        "rql": "ilike(name,*Microsoft*)",
        "limit": 5
      }
    }
  }' | sed -n 's/^data: //p' | jq '.result.structuredContent'

echo ""
echo ""

# Example 3: List available resources
echo "Example 3: List available resources"
echo "------------------------------------------------------------"

curl -s -X POST "$MCP_SERVER_URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-MPT-Authorization: $YOUR_API_TOKEN" \
  -H "X-MPT-Endpoint: $YOUR_API_ENDPOINT" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "marketplace_resources",
      "arguments": {}
    }
  }' | sed -n 's/^data: //p' | jq '.result.structuredContent.total_resources'

echo ""
echo ""
echo "============================================================"
echo "✅ Examples completed!"
echo "============================================================"
