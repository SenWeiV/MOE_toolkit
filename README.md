# MOE Toolkit

Cloud-hosted MOE Toolkit runtime and local connector for remote CSV analysis workflows.

## Components

- `moe-cloud-api`: FastAPI service for uploads, task execution, run status, and artifacts
- `moe-worker`: standalone queue worker that processes runs and launches curated tool containers
- `cleanup-job`: background cleanup loop for expired uploads
- `moe-connector`: local MCP-compatible connector for host tools

## Current Scope

- Queue-backed remote execution
- Curated Docker tools for CSV summaries and chart generation
- File upload, artifact download, and stale-claim recovery
- Docker Compose deployment for beta cloud environments

## User Install

Public beta page:

```text
${MOE_PUBLIC_BASE_URL}/beta
```

Install directly from the repo:

```bash
bash scripts/install-connector.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host codex-cli
```

Build a release package for other users:

```bash
bash scripts/build-connector-release.sh
```

That produces `dist/moe-connector-macos.tar.gz`. Users can unpack it and run:

```bash
bash install.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host codex-cli
```

## Beta Ops

Minimal admin page:

```text
${MOE_PUBLIC_BASE_URL}/admin/login
```

Issue a beta API key:

```bash
moe-beta-admin issue --owner-name "Alice" --contact "alice@example.com"
```

Batch-issue keys and export email templates:

```bash
moe-beta-admin bulk-issue --input-csv ./beta-users.csv --output-dir ./beta-batch
moe-beta-admin export-emails --output-dir ./beta-email-export --status active
```

Render the active key set for deployment:

```bash
MOE_API_KEYS_RAW="$(moe-beta-admin render-env)" bash scripts/deploy-cloud.sh
```

`bulk-issue` writes `issued_keys.csv`, `email_manifest.csv`, and `emails/*.txt` for operator follow-up.

To enable the hosted admin page during deploy, set:

```bash
export MOE_ADMIN_USERNAME=operator
export MOE_ADMIN_PASSWORD='<strong-password>'
export MOE_ADMIN_SESSION_SECRET='<long-random-secret>'
MOE_API_KEYS_RAW="$(moe-beta-admin render-env)" bash scripts/deploy-cloud.sh
```
