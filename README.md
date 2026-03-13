# MOE Toolkit

MOESkills CLI + Cloud API for curated remote analysis workflows.

## Components

- `moe-cloud-api`: FastAPI service for uploads, task execution, run status, and artifacts
- `moe-worker`: standalone queue worker that processes runs and launches curated tool containers
- `cleanup-job`: background cleanup loop for expired uploads
- `moeskills`: agent-first CLI for config, runs, registry queries, artifacts, and optional host adapters

## Current Scope

- Queue-backed remote execution
- Static curated tool registry with manifest-backed routing
- Curated Docker tools for CSV/XLSX summaries, chart generation, spreadsheet export, and Markdown reports
- File upload, artifact download, and stale-claim recovery
- Registry search and connector telemetry endpoints for beta debugging
- Docker Compose deployment for beta cloud environments

## User Install

详细使用说明见：[用户指南.md](./用户指南.md)

如需在本机保留不应提交的部署参数，可复制 `.env.local.example` 为 `.env.local`。

Public beta page:

```text
${MOE_PUBLIC_BASE_URL}/beta
```

Install directly from the repo:

```bash
bash scripts/install-connector.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY>
```

Run an agent task directly:

```bash
~/.local/bin/moeskills run \
  --task "分析这个 CSV 并生成趋势图" \
  --attach ./sales.csv \
  --wait \
  --json
```

Optional host integration for Codex CLI:

```bash
bash scripts/install-connector.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host codex-cli
```

OpenClaw users can install the same connector into a selected agent workspace:

```bash
bash scripts/install-connector.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host openclaw
```

If auto-discovery fails, pass the workspace explicitly:

```bash
bash scripts/install-connector.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host openclaw \
  --openclaw-workspace ~/.openclaw/workspace-your-agent
```

Build a release package for other users:

```bash
bash scripts/build-connector-release.sh
```

That produces `dist/moeskills-macos.tar.gz`. Users can unpack it and run:

```bash
bash install.sh \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY>
```

OpenClaw task artifacts download into the selected agent workspace under `MOE Outputs/`.

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

`bulk-issue` writes `issued_keys.csv`, `email_manifest.csv`, and `emails/*.txt` for admin follow-up.

To enable the hosted admin page during deploy, set:

```bash
export MOE_ADMIN_USERNAME='<admin-username>'
export MOE_ADMIN_PASSWORD='<strong-password>'
export MOE_ADMIN_SESSION_SECRET='<long-random-secret>'
MOE_API_KEYS_RAW="$(moe-beta-admin render-env)" bash scripts/deploy-cloud.sh
```
