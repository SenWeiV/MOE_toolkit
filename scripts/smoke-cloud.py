from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from moe_toolkit.connector.client import CloudClient
from moe_toolkit.schemas.common import ConnectorConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a cloud smoke test against MOE Toolkit.")
    parser.add_argument("--server-url", default="${MOE_PUBLIC_BASE_URL}")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--task", default="分析这个 CSV 并生成趋势图")
    return parser


async def run_smoke(server_url: str, api_key: str, output_dir: Path, task: str) -> int:
    config = ConnectorConfig(
        server_url=server_url,
        api_key=api_key,
        host_client="codex-cli",
        output_dir=output_dir,
        run_poll_interval_seconds=0.5,
        request_timeout_seconds=60,
    )
    client = CloudClient(config)

    with tempfile.TemporaryDirectory(prefix="moe-smoke-") as tmp_dir:
        source = Path(tmp_dir) / "sales.csv"
        source.write_text("month,value\n1,10\n2,20\n3,35\n", encoding="utf-8")

        health = await client.get_health()
        if not health.healthy or health.authenticated is False:
            print("Health check failed.", file=sys.stderr)
            return 1

        upload = await client.upload_file(source)
        accepted = await client.execute_task(
            task=task,
            attachments=[upload.upload_id],
            session_id="cloud-smoke-session",
        )
        run = await client.wait_for_run(accepted.run_id)
        if run.status != "success":
            print(f"Run failed: {run.model_dump(mode='json')}", file=sys.stderr)
            return 1

        artifacts = await client.get_artifacts(accepted.run_id)
        if len(artifacts) < 2:
            print(f"Expected at least 2 artifacts, got {len(artifacts)}", file=sys.stderr)
            return 1

        downloaded = []
        for artifact in artifacts:
            downloaded.append(await client.download_artifact(artifact, output_dir))

        print(f"Health authenticated: {health.authenticated}")
        print(f"Run ID: {run.run_id}")
        print(f"Artifacts: {[artifact.filename for artifact in artifacts]}")
        print(f"Downloaded: {[str(path) for path in downloaded]}")
        return 0


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else ROOT_DIR / ".smoke-downloads"
    output_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run_smoke(args.server_url, args.api_key, output_dir, args.task))


if __name__ == "__main__":
    raise SystemExit(main())
