# Custom Domain Setup for Google Cloud Run

This guide explains how to set up a custom domain for your MCP server running on Google Cloud Run.

## Prerequisites

- A registered domain name (e.g., `mcp.softwareone.com`)
- Access to your domain's DNS settings
- Appropriate permissions in your GCP project

## Step 1: Verify Domain Ownership

First, verify that you own the domain in Google Cloud:

```bash
# Verify domain ownership
gcloud domains verify mcp.softwareone.com
```

Follow the instructions to add a TXT record to your DNS to verify ownership.

## Step 2: Map Custom Domain to Cloud Run Service

```bash
# Set your variables
export GCP_PROJECT_ID="mpt-test-project"
export GCP_REGION="europe-west4"
export SERVICE_NAME="mpt-mcp"
export CUSTOM_DOMAIN="mcp.softwareone.com"

# Map the domain
gcloud run domain-mappings create \
  --service $SERVICE_NAME \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID
```

## Step 3: Configure DNS Records

After running the domain mapping command, Cloud Run will provide DNS records you need to add. Typically:

### For Root Domain (e.g., mcp.softwareone.com)

Add these records to your DNS:

```
Type: A
Name: mcp (or @ for root)
Value: [IP provided by Cloud Run]
TTL: 3600

Type: AAAA
Name: mcp (or @ for root)
Value: [IPv6 provided by Cloud Run]
TTL: 3600
```

### For Subdomain (e.g., api.mcp.softwareone.com)

```
Type: CNAME
Name: api.mcp
Value: ghs.googlehosted.com
TTL: 3600
```

## Step 4: Get DNS Configuration

To see what DNS records you need to add:

```bash
gcloud run domain-mappings describe \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID
```

This will output something like:

```yaml
status:
  resourceRecords:
  - name: mcp.softwareone.com
    rrdata: 216.239.32.21
    type: A
  - name: mcp.softwareone.com
    rrdata: 216.239.34.21
    type: A
  - name: mcp.softwareone.com
    rrdata: 2001:4860:4802:32::15
    type: AAAA
```

## Step 5: Wait for DNS Propagation

DNS changes can take 24-48 hours to propagate globally, but usually complete within a few hours.

Check DNS propagation:

```bash
# Check A record
dig mcp.softwareone.com A

# Check AAAA record  
dig mcp.softwareone.com AAAA

# Check CNAME record (if using subdomain)
dig api.mcp.softwareone.com CNAME
```

## Step 6: Verify SSL Certificate

Cloud Run automatically provisions and manages SSL certificates for custom domains. Check the status:

```bash
gcloud run domain-mappings describe \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID \
  --format="value(status.conditions)"
```

Wait for the certificate status to become "Ready". This can take 15-60 minutes after DNS records are configured.

## Step 7: Update Your Cursor MCP Configuration

Once the domain is active, update your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "softwareone-marketplace": {
      "url": "https://mcp.softwareone.com/mcp",
      "transport": "mcp",
      "timeout": 30000,
      "headers": {
        "X-MPT-Authorization": "your_api_token_here",
        "X-MPT-Endpoint": "https://api.platform.softwareone.com"
      }
    }
  }
}
```

## Troubleshooting

### Domain Mapping Not Working

```bash
# Check domain mapping status
gcloud run domain-mappings list \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID

# Check service details
gcloud run services describe $SERVICE_NAME \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID
```

### SSL Certificate Issues

If the SSL certificate is not provisioning:

1. Verify DNS records are correctly configured
2. Wait for DNS propagation (can take up to 48 hours)
3. Check that the domain ownership is verified
4. Ensure there are no conflicting DNS records

```bash
# Delete and recreate the domain mapping if needed
gcloud run domain-mappings delete \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID

# Then recreate it
gcloud run domain-mappings create \
  --service $SERVICE_NAME \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID
```

### DNS Not Resolving

Use online tools to check DNS propagation:
- https://www.whatsmydns.net/
- https://dnschecker.org/

## Managing Multiple Domains

You can map multiple domains to the same service:

```bash
# Add another domain
gcloud run domain-mappings create \
  --service $SERVICE_NAME \
  --domain api.mcp.softwareone.com \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID
```

## Removing a Custom Domain

```bash
gcloud run domain-mappings delete \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID
```

## Security Considerations

1. **Always use HTTPS**: Cloud Run automatically provides SSL/TLS
2. **Use strong API tokens**: Store in the `X-MPT-Authorization` header
3. **Consider IP allowlisting**: Use Cloud Armor for additional security
4. **Monitor access**: Use Cloud Logging to track API usage

## Example: Complete Setup Script

```bash
#!/bin/bash

# Configuration
export GCP_PROJECT_ID="mpt-test-project"
export GCP_REGION="europe-west4"
export SERVICE_NAME="mpt-mcp"
export CUSTOM_DOMAIN="mcp.softwareone.com"

echo "Setting up custom domain for Cloud Run..."

# 1. Verify domain ownership (follow interactive prompts)
echo "Step 1: Verifying domain ownership..."
gcloud domains verify $CUSTOM_DOMAIN

# 2. Create domain mapping
echo "Step 2: Creating domain mapping..."
gcloud run domain-mappings create \
  --service $SERVICE_NAME \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID

# 3. Get DNS records
echo "Step 3: DNS records to configure:"
gcloud run domain-mappings describe \
  --domain $CUSTOM_DOMAIN \
  --region $GCP_REGION \
  --project $GCP_PROJECT_ID \
  --format="table(status.resourceRecords)"

echo ""
echo "✅ Domain mapping created!"
echo "📋 Add the DNS records shown above to your domain provider"
echo "⏳ Wait for DNS propagation (15 min - 48 hours)"
echo "🔒 SSL certificate will be provisioned automatically"
```

## Resources

- [Cloud Run Custom Domains Documentation](https://cloud.google.com/run/docs/mapping-custom-domains)
- [Domain Verification](https://cloud.google.com/storage/docs/domain-name-verification)
- [SSL Certificate Management](https://cloud.google.com/run/docs/securing/using-custom-ssl-certificates)
