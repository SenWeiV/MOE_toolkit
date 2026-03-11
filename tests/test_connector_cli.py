from __future__ import annotations

import json
from pathlib import Path

import pytest

from moe_toolkit.connector import cli as cli_module
from moe_toolkit.schemas.common import (
    ArtifactRef,
    HealthComponent,
    HealthResponse,
    RoutePlan,
    RunRecord,
    TaskAccepted,
    UploadRef,
)


def bootstrap_workspace(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (path / "TOOLS.md").write_text("# Tools\n", encoding="utf-8")
    return path


def test_cli_configure_writes_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"

    exit_code = cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "codex-cli",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
        ]
    )

    assert exit_code == 0
    content = config_path.read_text(encoding="utf-8")
    assert 'server_url = "http://127.0.0.1:8080"' in content
    assert 'api_key = "secret-key"' in content


@pytest.mark.asyncio
async def test_cli_doctor_returns_success_with_healthy_cloud(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "codex-cli",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
        ]
    )
    async def fake_get_health(self) -> HealthResponse:  # noqa: ARG001
        return HealthResponse(
            service="moe-cloud",
            version="0.1.0",
            healthy=True,
            authenticated=True,
            components=[HealthComponent(name="api", healthy=True, detail="ok")],
        )

    monkeypatch.setattr(cli_module.CloudClient, "get_health", fake_get_health)

    exit_code = await cli_module.doctor_connector(config_path)

    assert exit_code == 0


def test_cli_install_and_uninstall_codex(tmp_path: Path, monkeypatch) -> None:
    codex_config = tmp_path / "config.toml"
    codex_config.write_text('model = "gpt-5.4"\n', encoding="utf-8")
    monkeypatch.setattr(cli_module, "get_codex_config_path", lambda home=None: codex_config)

    install_code = cli_module.main(
        [
            "install",
            "--host",
            "codex-cli",
            "--command-path",
            str(tmp_path / "bin" / "moe-connector"),
            "--config-path",
            str(tmp_path / ".moe-connector" / "config.toml"),
        ]
    )
    installed = codex_config.read_text(encoding="utf-8")
    uninstall_code = cli_module.main(["uninstall", "--host", "codex-cli"])
    removed = codex_config.read_text(encoding="utf-8")

    assert install_code == 0
    assert uninstall_code == 0
    assert "[mcp_servers.moe_toolkit]" in installed
    assert f'command = "{tmp_path / "bin" / "moe-connector"}"' in installed
    assert f'"{tmp_path / ".moe-connector" / "config.toml"}"' in installed
    assert "[mcp_servers.moe_toolkit]" not in removed


def test_cli_install_and_uninstall_openclaw(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace")
    config_path = tmp_path / ".moe-connector" / "config.toml"

    install_code = cli_module.main(
        [
            "install",
            "--host",
            "openclaw",
            "--workspace-path",
            str(workspace),
            "--command-path",
            str(tmp_path / "bin" / "moe-connector"),
            "--config-path",
            str(config_path),
        ]
    )
    tools_path = workspace / "TOOLS.md"
    wrapper_path = workspace / ".moe-toolkit" / "bin" / "moe-openclaw"
    installed = tools_path.read_text(encoding="utf-8")
    wrapper_content = wrapper_path.read_text(encoding="utf-8")

    uninstall_code = cli_module.main(
        [
            "uninstall",
            "--host",
            "openclaw",
            "--workspace-path",
            str(workspace),
        ]
    )
    removed = tools_path.read_text(encoding="utf-8")

    assert install_code == 0
    assert uninstall_code == 0
    assert "## MOE Toolkit" in installed
    assert "--workspace-path" in wrapper_content
    assert "## MOE Toolkit" not in removed
    assert wrapper_path.exists() is False


@pytest.mark.asyncio
async def test_cli_doctor_checks_openclaw_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace")
    cli_module.main(
        [
            "install",
            "--host",
            "openclaw",
            "--workspace-path",
            str(workspace),
            "--command-path",
            str(tmp_path / "bin" / "moe-connector"),
            "--config-path",
            str(tmp_path / "connector.toml"),
        ]
    )
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "openclaw",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
        ]
    )
    capsys.readouterr()

    async def fake_get_health(self) -> HealthResponse:  # noqa: ARG001
        return HealthResponse(
            service="moe-cloud",
            version="0.1.0",
            healthy=True,
            authenticated=True,
            components=[HealthComponent(name="api", healthy=True, detail="ok")],
        )

    monkeypatch.setattr(cli_module.CloudClient, "get_health", fake_get_health)

    exit_code = await cli_module.doctor_connector(
        config_path,
        hosts=["openclaw"],
        workspace_path=str(workspace),
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Host registration [openclaw]: True" in output
    assert f"OpenClaw workspace: {workspace.resolve()}" in output


def test_cli_openclaw_run_downloads_to_workspace_output_dir(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace")
    source = workspace / "sales.csv"
    source.write_text("month,value\n1,10\n", encoding="utf-8")
    config_path = tmp_path / "connector.toml"
    cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "openclaw",
            "--output-dir",
            str(tmp_path / "global-outputs"),
            "--config-path",
            str(config_path),
        ]
    )
    capsys.readouterr()

    async def fake_upload_file(self, source_path: Path) -> UploadRef:  # noqa: ARG001
        return UploadRef(
            upload_id=f"upload-{source_path.stem}",
            filename=source_path.name,
            size_bytes=source_path.stat().st_size,
            content_type="text/csv",
            expires_at="2026-03-12T00:00:00+00:00",
        )

    async def fake_execute_task(self, task: str, attachments: list[str], session_id: str | None = None) -> TaskAccepted:  # noqa: ARG001
        assert task == "分析这个 CSV 并生成趋势图"
        assert attachments == ["upload-sales"]
        assert session_id == "session-1"
        return TaskAccepted(
            run_id="run-1",
            status="queued",
            route_plan=RoutePlan(
                plan_id="plan-1",
                capabilities=["csv.analysis"],
                selected_images=["moe-tool-pandas"],
                execution_steps=["summarize"],
                explanation="test",
            ),
        )

    async def fake_wait_for_run(self, run_id: str) -> RunRecord:  # noqa: ARG001
        return RunRecord(
            run_id="run-1",
            status="success",
            task="分析这个 CSV 并生成趋势图",
            route_plan=RoutePlan(
                plan_id="plan-1",
                capabilities=["csv.analysis"],
                selected_images=["moe-tool-pandas"],
                execution_steps=["summarize"],
                explanation="test",
            ),
        )

    async def fake_get_artifacts(self, run_id: str) -> list[ArtifactRef]:  # noqa: ARG001
        return [
            ArtifactRef(
                artifact_id="artifact-1",
                run_id="run-1",
                filename="summary.json",
                media_type="application/json",
                size_bytes=12,
                download_url="/v1/runs/run-1/artifacts/artifact-1/download",
            )
        ]

    async def fake_download_artifact(self, artifact: ArtifactRef, output_dir: Path) -> Path:  # noqa: ARG001
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / f"{artifact.run_id}-{artifact.filename}"
        destination.write_text('{"ok":true}\n', encoding="utf-8")
        return destination

    monkeypatch.setattr(cli_module.CloudClient, "upload_file", fake_upload_file)
    monkeypatch.setattr(cli_module.CloudClient, "execute_task", fake_execute_task)
    monkeypatch.setattr(cli_module.CloudClient, "wait_for_run", fake_wait_for_run)
    monkeypatch.setattr(cli_module.CloudClient, "get_artifacts", fake_get_artifacts)
    monkeypatch.setattr(cli_module.CloudClient, "download_artifact", fake_download_artifact)

    exit_code = cli_module.main(
        [
            "openclaw",
            "run",
            "--workspace-path",
            str(workspace),
            "--task",
            "分析这个 CSV 并生成趋势图",
            "--attach",
            "sales.csv",
            "--session-id",
            "session-1",
            "--config-path",
            str(config_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    downloaded_path = Path(payload["downloaded_paths"][0])

    assert exit_code == 0
    assert payload["status"] == "success"
    assert downloaded_path.exists()
    assert downloaded_path.parent == workspace / "MOE Outputs"


def test_cli_openclaw_run_rejects_attachments_outside_workspace(tmp_path: Path, capsys) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace")
    outside = tmp_path / "outside.csv"
    outside.write_text("month,value\n1,10\n", encoding="utf-8")
    config_path = tmp_path / "connector.toml"
    cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "openclaw",
            "--output-dir",
            str(tmp_path / "global-outputs"),
            "--config-path",
            str(config_path),
        ]
    )

    exit_code = cli_module.main(
        [
            "openclaw",
            "run",
            "--workspace-path",
            str(workspace),
            "--task",
            "分析这个 CSV",
            "--attach",
            str(outside),
            "--config-path",
            str(config_path),
        ]
    )
    error = capsys.readouterr().err

    assert exit_code == 1
    assert "must stay inside the OpenClaw workspace" in error
