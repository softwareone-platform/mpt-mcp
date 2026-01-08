#!/bin/bash

# Example: Using the SSE Multi-Tenant MCP Server with curl
# This shows how to call the server with custom API credentials

# Configuration
MCP_SERVER_URL="http://localhost:8000/sse"
YOUR_API_TOKEN="your_api_token_here"
YOUR_API_ENDPOINT="https://api.platform.softwareone.com"

echo "============================================================"
echo "MCP SSE Multi-Tenant - curl Examples"
echo "============================================================"
echo ""

# Example 1: Get product count
echo "Example 1: Get product count"
echo "------------------------------------------------------------"

curl -X POST "$MCP_SERVER_URL" \
  -H "Content-Type: application/json" \
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
  }' | jq '.'

echo ""
echo ""

# Example 2: Search for Microsoft products
echo "Example 2: Search for Microsoft products"
echo "------------------------------------------------------------"

curl -X POST "$MCP_SERVER_URL" \
  -H "Content-Type: application/json" \
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
  }' | jq '.'

echo ""
echo ""

# Example 3: List available resources
echo "Example 3: List available resources"
echo "------------------------------------------------------------"

curl -X POST "$MCP_SERVER_URL" \
  -H "Content-Type: application/json" \
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
  }' | jq '.result.total_resources'

echo ""
echo ""
echo "============================================================"
echo "✅ Examples completed!"
echo "============================================================"

