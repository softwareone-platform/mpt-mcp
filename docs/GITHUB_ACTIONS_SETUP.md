# GitHub Actions Setup Guide

This guide explains how to configure GitHub Actions for automated testing and deployment of the MCP server to Google Cloud Run.

## Overview

We have two workflows:

1. **Test Workflow** (`.github/workflows/test.yml`) - Runs on every PR and push to main/master
2. **Deploy Workflow** (`.github/workflows/deploy.yml`) - Deploys to Cloud Run when tests pass on main/master

## Prerequisites

- GitHub repository with the MCP server code
- Google Cloud Project with Cloud Run enabled
- GitHub repository admin access (to configure secrets and settings)

## Step 1: Enable Workload Identity Federation (Recommended)

Instead of using service account keys, use Workload Identity Federation for secure, keyless authentication.

### 1.1 Create a Workload Identity Pool

```bash
export PROJECT_ID="mpt-test-project"
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
export POOL_NAME="github-actions-pool"
export PROVIDER_NAME="github-actions-provider"
export REPO_OWNER="your-github-username"
export REPO_NAME="mpt-mcp"

# Create pool
gcloud iam workload-identity-pools create $POOL_NAME \
  --project=$PROJECT_ID \
  --location="global" \
  --display-name="GitHub Actions Pool"

# Create provider
gcloud iam workload-identity-pools providers create-oidc $PROVIDER_NAME \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool=$POOL_NAME \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository_owner == '$REPO_OWNER'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

### 1.2 Create Service Account

```bash
export SERVICE_ACCOUNT="github-actions-sa"
export SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create service account
gcloud iam service-accounts create $SERVICE_ACCOUNT \
  --project=$PROJECT_ID \
  --display-name="GitHub Actions Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/cloudbuild.builds.builder"
```

### 1.3 Allow GitHub Actions to Impersonate Service Account

```bash
gcloud iam service-accounts add-iam-policy-binding $SERVICE_ACCOUNT_EMAIL \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${REPO_OWNER}/${REPO_NAME}"
```

### 1.4 Get Workload Identity Provider Resource Name

```bash
gcloud iam workload-identity-pools providers describe $PROVIDER_NAME \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool=$POOL_NAME \
  --format="value(name)"
```

This will output something like:
```
projects/123456789/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider
```

Save this value - you'll need it for GitHub secrets!

## Step 2: Configure GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions

Add the following secrets:

### Required Secrets

| Secret Name | Description | Example Value |
|------------|-------------|---------------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Workload Identity Provider resource name | `projects/123456789/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider` |
| `GCP_SERVICE_ACCOUNT` | Service account email | `github-actions-sa@mpt-test-project.iam.gserviceaccount.com` |
| `GCP_PROJECT_ID` | Your GCP project ID | `mpt-test-project` |
| `GCP_REGION` | Cloud Run region | `europe-west4` |

### Optional Secrets

| Secret Name | Description | Example Value |
|------------|-------------|---------------|
| `CODECOV_TOKEN` | Codecov upload token (for coverage reports) | Get from codecov.io |

## Step 3: Alternative - Using Service Account Key (Less Secure)

If you can't use Workload Identity Federation, you can use a service account key:

```bash
# Create service account
gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions Service Account"

# Grant permissions (same as above)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"

# ... (repeat other permissions from above)

# Create and download key
gcloud iam service-accounts keys create key.json \
  --iam-account=github-actions@${PROJECT_ID}.iam.gserviceaccount.com

# Copy the entire contents of key.json
cat key.json
```

Then modify `.github/workflows/deploy.yml` to use the key instead:

```yaml
- name: Authenticate to Google Cloud
  uses: google-github-actions/auth@v2
  with:
    credentials_json: ${{ secrets.GCP_SA_KEY }}
```

And add `GCP_SA_KEY` secret to GitHub with the entire JSON key content.

## Step 4: Test the Workflows

### Test PR Workflow

1. Create a new branch:
```bash
git checkout -b test-ci
```

2. Make a small change and push:
```bash
echo "# Test" >> README.md
git add README.md
git commit -m "Test CI"
git push origin test-ci
```

3. Create a Pull Request on GitHub
4. Check the "Actions" tab to see the test workflow running

### Test Deploy Workflow

1. Merge the PR to main/master
2. Check the "Actions" tab to see both test and deploy workflows running
3. Once complete, verify your service is deployed:

```bash
gcloud run services describe mpt-mcp \
  --region europe-west4 \
  --format='value(status.url)'
```

## Step 5: Monitor Deployments

### View Deployment History

Go to GitHub → Actions tab to see all workflow runs with:
- Test results
- Deployment status
- Service URLs
- Image tags

### View Cloud Run Logs

```bash
# View recent logs
gcloud run services logs read mpt-mcp --region europe-west4 --limit 100

# Follow logs in real-time (requires beta)
gcloud beta run services logs tail mpt-mcp --region europe-west4
```

## Workflow Details

### Test Workflow (`.github/workflows/test.yml`)

**Triggers:**
- On pull requests to main/master
- On push to main/master

**Steps:**
1. Checkout code
2. Setup Python 3.12
3. Install dependencies
4. Run linter (ruff)
5. Run type checker (mypy)
6. Run tests with coverage
7. Upload coverage reports

### Deploy Workflow (`.github/workflows/deploy.yml`)

**Triggers:**
- On push to main/master (after tests pass)
- Manual trigger (workflow_dispatch)

**Steps:**
1. **Test Job:**
   - Run full test suite
   - Must pass before deployment

2. **Deploy Job:**
   - Authenticate to Google Cloud
   - Build Docker image
   - Push to Google Container Registry
   - Deploy to Cloud Run
   - Output service URL

## Troubleshooting

### Workflow Fails: "Permission Denied"

Check that your service account has all necessary roles:

```bash
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:github-actions-sa@${PROJECT_ID}.iam.gserviceaccount.com"
```

### Workload Identity Authentication Fails

Verify the attribute condition matches your repository:

```bash
gcloud iam workload-identity-pools providers describe $PROVIDER_NAME \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool=$POOL_NAME
```

### Deployment Succeeds But Service Not Accessible

Check if the service is publicly accessible:

```bash
gcloud run services get-iam-policy mpt-mcp --region=europe-west4
```

It should include:
```yaml
bindings:
- members:
  - allUsers
  role: roles/run.invoker
```

If not, run:
```bash
gcloud run services add-iam-policy-binding mpt-mcp \
  --region=europe-west4 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

## Security Best Practices

1. **Use Workload Identity Federation** instead of service account keys
2. **Limit service account permissions** to only what's needed
3. **Use branch protection rules** to require PR reviews before merge
4. **Enable signed commits** for additional security
5. **Regularly rotate secrets** if using service account keys
6. **Monitor deployments** using Cloud Logging and Cloud Monitoring
7. **Use separate environments** (dev, staging, prod) with different workflows

## Advanced Configuration

### Deploy to Multiple Environments

You can extend the deploy workflow to support multiple environments:

```yaml
name: Deploy

on:
  push:
    branches:
      - main      # Production
      - staging   # Staging
      - develop   # Development

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Set environment
        id: env
        run: |
          if [ "${{ github.ref }}" == "refs/heads/main" ]; then
            echo "env=production" >> $GITHUB_OUTPUT
            echo "service=mpt-mcp" >> $GITHUB_OUTPUT
          elif [ "${{ github.ref }}" == "refs/heads/staging" ]; then
            echo "env=staging" >> $GITHUB_OUTPUT
            echo "service=mpt-mcp-staging" >> $GITHUB_OUTPUT
          else
            echo "env=development" >> $GITHUB_OUTPUT
            echo "service=mpt-mcp-dev" >> $GITHUB_OUTPUT
          fi
      
      - name: Deploy
        run: |
          gcloud run deploy ${{ steps.env.outputs.service }} \
            --image gcr.io/${{ secrets.GCP_PROJECT_ID }}/mpt-mcp:${{ github.sha }} \
            --region ${{ secrets.GCP_REGION }}
```

### Add Slack Notifications

Add this step to notify your team:

```yaml
- name: Notify Slack
  if: always()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    text: 'Deployment to Cloud Run'
    webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [Cloud Run Deployment](https://cloud.google.com/run/docs/deploying)
- [GitHub Actions for GCP](https://github.com/google-github-actions)
