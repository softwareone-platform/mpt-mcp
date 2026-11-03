# Deployment

The HTTP server runs on Google Cloud Run as the `mpt-mcp` service, published at `https://mcp.platform.softwareone.com/mcp`. The stdio server is not deployed; users run it locally (see [local-development.md](local-development.md)).

## Image

The [`Dockerfile`](../Dockerfile) is multi-stage: the `prod` stage (the default) installs only runtime dependencies, exposes port `8080`, has a `/health` healthcheck and runs `python -m mpt_mcp.runtime.runner`. The `dev` stage adds the dev dependencies and is the one `compose.yaml` uses.

## Workflow

[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) deploys on tags and on manual dispatch:

1. runs `make check` and `make test`
2. builds the `prod` image and pushes it to `gcr.io/<project>/mpt-mcp` with the commit SHA and `latest` tags
3. deploys it to Cloud Run with `gcloud run deploy mpt-mcp` (2 GiB, 1 CPU, 0–10 instances, unauthenticated access, since clients authenticate with their own Marketplace token)

The release and deploy flow is still to be decided (see the `TBD` note at the top of the workflow). Today:

- both `release/*` and `test/*` tags deploy to the same production service; do not push `test/*` tags expecting a separate environment
- secrets are passed to Cloud Run with `--set-env-vars`, not Secret Manager

## Configuration

GitHub secrets used by the workflow:

| Secret | Purpose |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT` | Authentication to Google Cloud |
| `GCP_PROJECT_ID`, `GCP_REGION` | Container registry project and Cloud Run region |
| `ANALYTICS_DATABASE_URL` | Optional; enables analytics. A `?host=/cloudsql/<project>:<region>:<instance>` URL also attaches the Cloud SQL instance |
| `GITBOOK_API_KEY`, `GITBOOK_SPACE_ID`, `GITBOOK_PUBLIC_URL` | Optional; enable the documentation tools |

Cloud Run sets `PORT`, which the server listens on. Analytics migrations run when the new revision starts, see [migrations.md](migrations.md).
