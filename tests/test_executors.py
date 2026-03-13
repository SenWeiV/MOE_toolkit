from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from moe_toolkit.cloud.executors import (
    DockerExecutor,
    ExecutionContext,
    InlineExecutor,
    detect_media_type,
    prepare_run_workspace,
    run_docker_command,
)
from moe_toolkit.schemas.common import RemoteTaskRequest, RoutePlan


def build_route_plan(*, selected_images: list[str] | None = None) -> RoutePlan:
    images = selected_images or ["moe-tool-pandas"]
    return RoutePlan(
        plan_id="plan-1",
        capabilities=["csv_parse", "data_analysis"],
        selected_images=images,
        selected_tools=[image.removeprefix("moe-tool-") for image in images],
        execution_steps=images.copy(),
        selection_reason="test",
        explanation="test plan",
    )


def test_prepare_run_workspace_copies_uploads_and_writes_run_payload(tmp_path) -> None:
    source = tmp_path / "sales.csv"
    source.write_text("month,value\n1,10\n2,20\n", encoding="utf-8")
    request = RemoteTaskRequest(
        task="分析 CSV",
        attachments=["upload-1"],
        session_id="session-1",
        output_preferences={"format": "json"},
    )

    context = prepare_run_workspace(
        storage_root=tmp_path,
        run_id="run-1",
        request=request,
        upload_paths={"upload-1": source},
        route_plan=build_route_plan(),
    )

    copied = context.input_dir / "01-sales.csv"
    manifest_path = context.run_root / "run.json"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert context.artifacts_dir.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["task"] == "分析 CSV"
    assert payload["attachments"] == [
        {
            "upload_id": "upload-1",
            "source_name": "sales.csv",
            "workspace_name": "01-sales.csv",
        }
    ]
    assert payload["route_plan"]["selected_images"] == ["moe-tool-pandas"]


@pytest.mark.asyncio
async def test_inline_executor_creates_summary_and_chart_artifacts(tmp_path) -> None:
    source = tmp_path / "sales.csv"
    source.write_text("month,value\n1,10\n2,20\n3,30\n", encoding="utf-8")
    request = RemoteTaskRequest(
        task="分析这个 CSV 并生成趋势图",
        attachments=["upload-1"],
    )
    context = prepare_run_workspace(
        storage_root=tmp_path,
        run_id="run-1",
        request=request,
        upload_paths={"upload-1": source},
        route_plan=build_route_plan(selected_images=["moe-tool-pandas", "moe-tool-matplotlib"]),
    )

    await InlineExecutor().execute(context)

    summary_path = context.artifacts_dir / "01-sales-summary.json"
    chart_path = context.artifacts_dir / "01-sales-chart.svg"
    assert summary_path.exists()
    assert chart_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["rows"] == 3
    assert "value" in summary["numeric_columns"]


@pytest.mark.asyncio
async def test_inline_executor_creates_spreadsheet_and_markdown_artifacts(tmp_path) -> None:
    source = tmp_path / "sales.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["month", "value"])
    sheet.append([1, 10])
    sheet.append([2, 20])
    workbook.save(source)
    request = RemoteTaskRequest(
        task="读取这个 Excel 并生成 Markdown report",
        attachments=["upload-1"],
    )
    context = prepare_run_workspace(
        storage_root=tmp_path,
        run_id="run-1",
        request=request,
        upload_paths={"upload-1": source},
        route_plan=build_route_plan(
            selected_images=["moe-tool-openpyxl", "moe-tool-markdown-report"]
        ),
    )

    await InlineExecutor().execute(context)

    summary_path = context.artifacts_dir / "01-sales-summary.json"
    spreadsheet_path = context.artifacts_dir / "01-sales-report.xlsx"
    report_path = context.artifacts_dir / "run-report.md"
    assert summary_path.exists()
    assert spreadsheet_path.exists()
    assert report_path.exists()
    assert "MOE Toolkit Run Report" in report_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_docker_executor_builds_expected_commands(tmp_path) -> None:
    commands: list[list[str]] = []

    async def fake_runner(command: list[str]) -> None:
        commands.append(command)

    request = RemoteTaskRequest(task="分析 CSV", attachments=[])
    context = prepare_run_workspace(
        storage_root=tmp_path,
        run_id="run-1",
        request=request,
        upload_paths={},
        route_plan=build_route_plan(
            selected_images=["moe-tool-pandas", "moe-tool-matplotlib"]
        ),
    )

    executor = DockerExecutor(
        docker_binary="docker-test",
        network_mode="bridge",
        runner=fake_runner,
    )
    await executor.execute(context)

    assert commands == [
        [
            "docker-test",
            "run",
            "--rm",
            "--network",
            "bridge",
            "-v",
            f"{context.run_root}:/work",
            "-w",
            "/work",
            "moe-tool-pandas",
        ],
        [
            "docker-test",
            "run",
            "--rm",
            "--network",
            "bridge",
            "-v",
            f"{context.run_root}:/work",
            "-w",
            "/work",
            "moe-tool-matplotlib",
        ],
    ]


@pytest.mark.asyncio
async def test_docker_executor_maps_container_storage_root_to_host_path() -> None:
    commands: list[list[str]] = []

    async def fake_runner(command: list[str]) -> None:
        commands.append(command)

    request = RemoteTaskRequest(task="分析 CSV", attachments=[])
    context = ExecutionContext(
        run_id="run-1",
        request=request,
        route_plan=build_route_plan(selected_images=["moe-tool-pandas"]),
        run_root=Path("/srv/moe/runs/run-1"),
        input_dir=Path("/srv/moe/runs/run-1/inputs"),
        artifacts_dir=Path("/srv/moe/runs/run-1/artifacts"),
    )

    executor = DockerExecutor(
        docker_binary="/usr/bin/docker",
        storage_root=Path("/srv/moe"),
        host_storage_root=Path("/opt/moe-toolkit/data"),
        network_mode="none",
        runner=fake_runner,
    )
    await executor.execute(context)

    assert commands == [
        [
            "/usr/bin/docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            "/opt/moe-toolkit/data/runs/run-1:/work",
            "-w",
            "/work",
            "moe-tool-pandas",
        ]
    ]


def test_detect_media_type_and_number_parsing_helpers() -> None:
    assert detect_media_type(Path("report.json")) == "application/json"
    assert detect_media_type(Path("chart.svg")) == "image/svg+xml"
    assert detect_media_type(Path("report.md")) == "text/markdown"
    assert detect_media_type(Path("table.xlsx")) == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert detect_media_type(Path("blob.bin")) == "application/octet-stream"
    assert InlineExecutor._is_number("12.5") is True
    assert InlineExecutor._is_number("not-a-number") is False


@pytest.mark.asyncio
async def test_run_docker_command_raises_runtime_error_on_failure(monkeypatch) -> None:
    class FakeProcess:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"stdout", b"stderr"

    async def fake_create_subprocess_exec(*args, **kwargs):  # noqa: ARG001
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError) as exc_info:
        await run_docker_command(["docker", "run", "broken"])

    message = str(exc_info.value)
    assert "Docker command failed: docker run broken" in message
    assert "stdout=stdout" in message
    assert "stderr=stderr" in message
