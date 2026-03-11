from __future__ import annotations

from pathlib import Path

import pytest

from moe_toolkit.connector import mcp_server
from moe_toolkit.schemas.common import ArtifactRef, HealthComponent, HealthResponse, RoutePlan, RunRecord, UploadRef


@pytest.mark.asyncio
async def test_build_server_registers_expected_tools(tmp_path: Path) -> None:
    server = mcp_server.build_server(config_path=tmp_path / "connector.toml")

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == [
        "service.health",
        "service.configure",
        "task.execute",
        "run.get_status",
        "run.get_artifacts",
    ]


@pytest.mark.asyncio
async def test_mcp_service_configure_and_health_tools(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "connector.toml"
    server = mcp_server.build_server(config_path=config_path)

    async def fake_get_health(self) -> HealthResponse:  # noqa: ARG001
        return HealthResponse(
            service="moe-cloud",
            version="0.1.0",
            healthy=True,
            authenticated=True,
            components=[HealthComponent(name="api", healthy=True, detail="ok")],
        )

    monkeypatch.setattr(mcp_server.CloudClient, "get_health", fake_get_health)

    _, configure_payload = await server.call_tool(
        "service.configure",
        {
            "server_url": "http://testserver",
            "api_key": "secret-key",
            "host_client": "codex-cli",
            "output_dir": str(tmp_path / "outputs"),
        },
    )
    _, health_payload = await server.call_tool("service.health", {})

    assert configure_payload["status"] == "configured"
    assert Path(configure_payload["config_path"]) == config_path
    assert config_path.exists()
    assert health_payload["healthy"] is True
    assert health_payload["authenticated"] is True


@pytest.mark.asyncio
async def test_mcp_task_and_run_tools_delegate_to_cloud_client(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    server = mcp_server.build_server(config_path=config_path)

    _, _ = await server.call_tool(
        "service.configure",
        {
            "server_url": "http://testserver",
            "api_key": "secret-key",
            "host_client": "codex-cli",
            "output_dir": str(output_dir),
        },
    )

    local_source = tmp_path / "sales.csv"
    local_source.write_text("month,value\n1,10\n", encoding="utf-8")

    route_plan = RoutePlan(
        plan_id="plan-1",
        capabilities=["csv_parse", "data_analysis"],
        selected_images=["moe-tool-pandas"],
        execution_steps=["moe-tool-pandas"],
        explanation="test",
    )
    artifact = ArtifactRef(
        artifact_id="artifact-1",
        run_id="run-1",
        filename="sales-summary.json",
        media_type="application/json",
        size_bytes=12,
        download_url="http://testserver/v1/artifacts/artifact-1/download",
    )
    run_record = RunRecord(
        run_id="run-1",
        status="success",
        task="分析 CSV",
        route_plan=route_plan,
        artifact_ids=["artifact-1"],
    )

    async def fake_upload_file(self, source: Path) -> UploadRef:  # noqa: ARG001
        return UploadRef(
            upload_id=f"upload-{source.stem}",
            filename=source.name,
            size_bytes=source.stat().st_size,
            content_type="text/csv",
            expires_at=run_record.created_at,
        )

    async def fake_execute_task(self, task: str, attachments: list[str], session_id: str | None = None):  # noqa: ARG001
        assert task == "分析 CSV"
        assert attachments == ["upload-sales"]
        assert session_id == "session-1"
        return type("Accepted", (), {"run_id": "run-1", "status": "queued", "route_plan": route_plan})()

    async def fake_wait_for_run(self, run_id: str) -> RunRecord:  # noqa: ARG001
        return run_record

    async def fake_get_run(self, run_id: str) -> RunRecord:  # noqa: ARG001
        return run_record

    async def fake_get_artifacts(self, run_id: str) -> list[ArtifactRef]:  # noqa: ARG001
        return [artifact]

    async def fake_download_artifact(self, artifact_ref: ArtifactRef, target_dir: Path) -> Path:  # noqa: ARG001
        destination = target_dir / f"{artifact_ref.run_id}-{artifact_ref.filename}"
        destination.write_text("{}", encoding="utf-8")
        return destination

    monkeypatch.setattr(mcp_server.CloudClient, "upload_file", fake_upload_file)
    monkeypatch.setattr(mcp_server.CloudClient, "execute_task", fake_execute_task)
    monkeypatch.setattr(mcp_server.CloudClient, "wait_for_run", fake_wait_for_run)
    monkeypatch.setattr(mcp_server.CloudClient, "get_run", fake_get_run)
    monkeypatch.setattr(mcp_server.CloudClient, "get_artifacts", fake_get_artifacts)
    monkeypatch.setattr(mcp_server.CloudClient, "download_artifact", fake_download_artifact)

    _, execute_payload = await server.call_tool(
        "task.execute",
        {
            "task": "分析 CSV",
            "attachments": [str(local_source)],
            "session_id": "session-1",
        },
    )
    _, status_payload = await server.call_tool("run.get_status", {"run_id": "run-1"})
    _, artifacts_payload = await server.call_tool("run.get_artifacts", {"run_id": "run-1"})

    assert execute_payload["status"] == "success"
    assert execute_payload["run_id"] == "run-1"
    assert len(execute_payload["downloaded_paths"]) == 1
    assert status_payload["status"] == "success"
    assert status_payload["run_id"] == "run-1"
    assert artifacts_payload["run_id"] == "run-1"
    assert len(artifacts_payload["artifacts"]) == 1
    assert Path(artifacts_payload["downloaded_paths"][0]).exists()


def test_run_server_invokes_fastmcp_run(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def run(self) -> None:
            captured["ran"] = True

    def fake_build_server(config_path: Path) -> FakeServer:
        captured["config_path"] = config_path
        return FakeServer()

    monkeypatch.setattr(mcp_server, "build_server", fake_build_server)

    mcp_server.run_server(tmp_path / "connector.toml")

    assert captured == {
        "config_path": tmp_path / "connector.toml",
        "ran": True,
    }
