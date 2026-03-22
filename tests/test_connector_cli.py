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


def test_cli_config_show_returns_json(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    cli_module.main(
        [
            "config",
            "set",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
            "--json",
        ]
    )
    capsys.readouterr()

    exit_code = cli_module.main(
        [
            "config",
            "show",
            "--config-path",
            str(config_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["server_url"] == "http://127.0.0.1:8080"
    assert payload["api_key"] == "secret-key"


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


def test_cli_run_wait_downloads_artifacts_and_returns_json(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    source = tmp_path / "sales.csv"
    source.write_text("month,value\n1,10\n", encoding="utf-8")
    cli_module.main(
        [
            "config",
            "set",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--output-dir",
            str(output_dir),
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
                capabilities=["data_analysis", "visualization"],
                selected_images=["moe-tool-pandas", "moe-tool-matplotlib"],
                selected_tools=["pandas", "matplotlib"],
                execution_steps=["pandas", "matplotlib"],
                selection_reason="matched",
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
                capabilities=["data_analysis", "visualization"],
                selected_images=["moe-tool-pandas", "moe-tool-matplotlib"],
                selected_tools=["pandas", "matplotlib"],
                execution_steps=["pandas", "matplotlib"],
                selection_reason="matched",
                explanation="test",
            ),
            artifact_ids=["artifact-1"],
        )

    async def fake_get_artifacts(self, run_id: str) -> list[ArtifactRef]:  # noqa: ARG001
        return [
            ArtifactRef(
                artifact_id="artifact-1",
                run_id="run-1",
                filename="sales-summary.json",
                media_type="application/json",
                size_bytes=2,
                download_url="http://testserver/v1/artifacts/artifact-1/download",
            )
        ]

    async def fake_download_artifact(self, artifact: ArtifactRef, destination_dir: Path) -> Path:  # noqa: ARG001
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{artifact.run_id}-{artifact.filename}"
        destination.write_text("{}", encoding="utf-8")
        return destination

    monkeypatch.setattr(cli_module.CloudClient, "upload_file", fake_upload_file)
    monkeypatch.setattr(cli_module.CloudClient, "execute_task", fake_execute_task)
    monkeypatch.setattr(cli_module.CloudClient, "wait_for_run", fake_wait_for_run)
    monkeypatch.setattr(cli_module.CloudClient, "get_artifacts", fake_get_artifacts)
    monkeypatch.setattr(cli_module.CloudClient, "download_artifact", fake_download_artifact)

    exit_code = cli_module.main(
        [
            "run",
            "--task",
            "分析这个 CSV 并生成趋势图",
            "--attach",
            str(source),
            "--session-id",
            "session-1",
            "--config-path",
            str(config_path),
            "--wait",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["run_id"] == "run-1"
    assert payload["downloaded_paths"] == [str(output_dir / "run-1-sales-summary.json")]


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
    capsys.readouterr()

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
    captured = capsys.readouterr()

    assert exit_code == cli_module.EXIT_CONFIG
    payload = json.loads(captured.out)
    assert payload["error_code"] == "invalid_runtime_input"
    assert "must stay inside the OpenClaw workspace" in payload["message"]


def test_cli_runs_wait_downloads_artifacts_and_returns_json(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    cli_module.main(
        [
            "config",
            "set",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
        ]
    )
    capsys.readouterr()

    async def fake_wait_for_run(self, run_id: str) -> RunRecord:  # noqa: ARG001
        assert run_id == "run-1"
        return RunRecord(
            run_id="run-1",
            status="success",
            task="分析这个 CSV 并生成趋势图",
            route_plan=RoutePlan(
                plan_id="plan-1",
                capabilities=["data_analysis"],
                selected_images=["moe-tool-pandas"],
                selected_tools=["pandas"],
                execution_steps=["pandas"],
                selection_reason="matched",
                explanation="test",
            ),
            artifact_ids=["artifact-1"],
        )

    async def fake_get_artifacts(self, run_id: str) -> list[ArtifactRef]:  # noqa: ARG001
        return [
            ArtifactRef(
                artifact_id="artifact-1",
                run_id="run-1",
                filename="sales-summary.json",
                media_type="application/json",
                size_bytes=2,
                download_url="http://testserver/v1/artifacts/artifact-1/download",
            )
        ]

    async def fake_download_artifact(self, artifact: ArtifactRef, destination_dir: Path) -> Path:  # noqa: ARG001
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{artifact.run_id}-{artifact.filename}"
        destination.write_text("{}", encoding="utf-8")
        return destination

    monkeypatch.setattr(cli_module.CloudClient, "wait_for_run", fake_wait_for_run)
    monkeypatch.setattr(cli_module.CloudClient, "get_artifacts", fake_get_artifacts)
    monkeypatch.setattr(cli_module.CloudClient, "download_artifact", fake_download_artifact)

    exit_code = cli_module.main(
        [
            "runs",
            "wait",
            "run-1",
            "--config-path",
            str(config_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["run_id"] == "run-1"
    assert payload["downloaded_paths"] == [str(output_dir / "run-1-sales-summary.json")]


def test_cli_repl_applies_session_defaults_to_dispatched_commands(tmp_path: Path) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    commands = iter(
        [
            f"use config {config_path}",
            f"use output-dir {output_dir}",
            "run --task ping",
            "state",
            "exit",
        ]
    )
    dispatched: list[list[str]] = []
    printed: list[str] = []

    def fake_input(_prompt: str) -> str:
        return next(commands)

    def fake_print(message: str = "") -> None:
        printed.append(message)

    def fake_dispatch(argv: list[str]) -> int:
        dispatched.append(argv)
        return 0

    exit_code = cli_module.run_repl(
        input_fn=fake_input,
        print_fn=fake_print,
        dispatch_command=fake_dispatch,
    )

    assert exit_code == 0
    assert dispatched == [["run", "--task", "ping", "--config-path", str(config_path), "--output-dir", str(output_dir)]]
    assert any("config_path" in line for line in printed)
    assert any(str(output_dir) in line for line in printed)
