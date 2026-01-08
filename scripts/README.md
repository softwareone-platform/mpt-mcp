# Scripts

Utility scripts for deployment and operations.

## ⚠️ Important Security Notice

**The `scripts/` folder is NOT published to GitHub** (excluded in `.gitignore`).

This folder may contain:
- Deployment scripts with infrastructure configuration
- Environment setup files with credentials
- Operational tools with sensitive settings

## 📁 Folder Structure

```
scripts/
├── docs/                          # Documentation (gitignored)
│   └── how-to-get-github-secrets.md  # GCP & GitHub Actions setup guide
├── deploy-gcp.sh                  # Cloud Run deployment
├── logs-gcp.sh                    # View Cloud Run logs
├── set-env.sh                     # Environment variables
└── README.md                      # This file (published)
```

## 📁 Available Scripts

### `set-env.sh` (Gitignored - Create from Template)

Environment variables configuration for deployment.

**⚠️ IMPORTANT**: This script must be **sourced**, not executed!

```bash
# ✅ Correct way:
source scripts/set-env.sh

# ❌ Wrong way (won't work):
./scripts/set-env.sh
```

**Setup**:
```bash
# 1. Copy the template
cp scripts/set-env.sh scripts/set-env.sh

# 2. Edit and fill in your values
nano scripts/set-env.sh

# 3. Source the file (loads variables into your current shell)
source scripts/set-env.sh

# 4. Verify variables are set
echo $GCP_PROJECT_ID
echo $GCP_REGION
```

**Required Variables**:
- `GCP_PROJECT_ID` - Your Google Cloud project ID
- `GCP_REGION` - Deployment region (no default for security)

**Optional Variables**:
- `GCP_SERVICE_NAME` - Custom service name (defaults to `mpt-mcp`)

### `deploy-gcp.sh`

Deploy the MCP server to Google Cloud Run.

**Prerequisites**:
- Google Cloud SDK (`gcloud`) installed
- Authenticated to GCP: `gcloud auth login`
- Environment variables set (use `set-env.sh`)

**Usage**:
```bash
# Set environment variables first
source scripts/set-env.sh

# Deploy
./scripts/deploy-gcp.sh
```

### `logs-gcp.sh`

View Cloud Run logs for the deployed MCP server.

**Usage**:
```bash
# View recent logs
export GCP_REGION="europe-west4"
./scripts/logs-gcp.sh

# Follow logs in real-time
./scripts/logs-gcp.sh --follow

# Limit number of log entries
./scripts/logs-gcp.sh --limit 50
```

## 🔒 Security Best Practices

1. **Never commit `set-env.sh`** - It contains credentials
2. **Use strong tokens** - Rotate API tokens regularly
3. **Limit access** - Only authorized team members should have deployment access
4. **Audit deployments** - Track who deployed what and when
5. **Use separate environments** - Different credentials for dev/staging/prod

## 🚀 Quick Start

First-time deployment:

```bash
# 1. Create your environment file
cp scripts/set-env.sh scripts/set-env.sh
nano scripts/set-env.sh  # Edit with your values

# 2. Load environment
source scripts/set-env.sh

# 3. Deploy
./scripts/deploy-gcp.sh

# 4. Verify deployment
curl $(gcloud run services describe mpt-mcp --region $GCP_REGION --format 'value(status.url)')/health

# 5. View logs
./scripts/logs-gcp.sh --limit 20
```

## 📊 Multiple Environments

Deploy to different environments using service names:

```bash
# Development
export GCP_SERVICE_NAME="mpt-mcp-dev"
export GCP_REGION="europe-west4"
./scripts/deploy-gcp.sh

# Staging
export GCP_SERVICE_NAME="mpt-mcp-staging"
export GCP_REGION="europe-west3"
./scripts/deploy-gcp.sh

# Production
export GCP_SERVICE_NAME="mpt-mcp"
export GCP_REGION="europe-west1"
./scripts/deploy-gcp.sh
```

## 🆘 Troubleshooting

### "gcloud CLI not found"
```bash
# Install Google Cloud SDK
# macOS
brew install google-cloud-sdk

# Or download from: https://cloud.google.com/sdk/docs/install
```

### "Please set GCP_PROJECT_ID"
```bash
# Set required environment variables
export GCP_PROJECT_ID="your-project"
export GCP_REGION="europe-west4"
```

### "Permission denied"
```bash
# Make scripts executable
chmod +x scripts/*.sh

# Authenticate to GCP
gcloud auth login
```

### "Build failed"
```bash
# Check Docker is working
docker --version

# Check you're in the right directory
ls Dockerfile  # Should exist in project root

# Verify GCP permissions
gcloud projects get-iam-policy $GCP_PROJECT_ID
```

## 📚 Related Documentation

- [Main README](../README.md) - Project overview and setup
- [GitHub Secrets Setup](docs/how-to-get-github-secrets.md) - **Complete guide for GCP & GitHub Actions setup**
- [GitHub Actions Setup](../docs/GITHUB_ACTIONS_SETUP.md) - CI/CD configuration details
- [Custom Domain Setup](../docs/CUSTOM_DOMAIN.md) - Configure custom domain
