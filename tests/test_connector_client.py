from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from moe_toolkit.cloud.app import create_app
from moe_toolkit.cloud.settings import CloudSettings
from moe_toolkit.connector.client import CloudClient
from moe_toolkit.schemas.common import ConnectorConfig


@pytest.mark.asyncio
async def test_cloud_client_uses_configured_api_key() -> None:
    app: FastAPI = create_app(CloudSettings(api_keys_raw="alpha-key"))
    transport = httpx.ASGITransport(app=app)
    config = ConnectorConfig(
        server_url="http://testserver",
        api_key="alpha-key",
        host_client="codex-cli",
    )

    async with app.router.lifespan_context(app):
        health = await CloudClient(config, transport=transport).get_health()

    assert health.authenticated is True
    assert health.healthy is True


@pytest.mark.asyncio
async def test_cloud_client_executes_task_and_downloads_artifacts(tmp_path) -> None:
    app: FastAPI = create_app(
        CloudSettings(
            api_keys_raw="alpha-key",
            storage_root=tmp_path / "cloud",
            public_base_url="http://example.test:8080",
            queue_poll_interval_seconds=0.01,
        )
    )
    transport = httpx.ASGITransport(app=app)
    source = tmp_path / "sales.csv"
    source.write_text("month,value\n1,10\n2,20\n3,30\n", encoding="utf-8")
    output_dir = tmp_path / "downloads"
    config = ConnectorConfig(
        server_url="http://testserver",
        api_key="alpha-key",
        host_client="codex-cli",
        output_dir=output_dir,
        run_poll_interval_seconds=0.01,
    )
    client = CloudClient(config, transport=transport)

    async with app.router.lifespan_context(app):
        upload = await client.upload_file(source)
        accepted = await client.execute_task(
            task="分析这个 CSV 并生成趋势图",
            attachments=[upload.upload_id],
            session_id="session-1",
        )
        assert accepted.status == "queued"
        run = await client.wait_for_run(accepted.run_id)
        artifacts = await client.get_artifacts(accepted.run_id)
        downloaded = await client.download_artifact(artifacts[0], output_dir)

    assert run.status == "success"
    assert artifacts
    assert downloaded.exists()
    assert downloaded.parent == output_dir
