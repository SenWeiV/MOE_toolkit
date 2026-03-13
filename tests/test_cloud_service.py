from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from moe_toolkit.cloud.executors import InlineExecutor
from moe_toolkit.cloud.services import CloudService
from moe_toolkit.schemas.common import RemoteTaskRequest, TelemetryEvent


@pytest.mark.asyncio
async def test_cloud_service_processes_runs_from_queue(tmp_path) -> None:
    service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
    )
    await service.start()
    try:
        upload = service.save_upload(
            filename="sales.csv",
            content_type="text/csv",
            payload=b"month,value\n1,10\n2,20\n",
        )
        run = service.create_run(
            RemoteTaskRequest(task="分析这个 CSV 并生成趋势图", attachments=[upload.upload_id])
        )
        assert run.status == "queued"

        for _ in range(30):
            current = service.get_run(run.run_id)
            if current.status == "success":
                break
            await asyncio.sleep(0.01)

        assert service.get_run(run.run_id).status == "success"
        artifacts = service.list_artifacts(run.run_id)
        assert len(artifacts) == 2
        assert {artifact.media_type for artifact in artifacts} == {
            "application/json",
            "image/svg+xml",
        }
        assert service.state.run_roots[run.run_id].joinpath("run.json").exists()
        route_logs = service.list_route_decisions()
        assert route_logs[-1]["selected_tools"] == ["pandas", "matplotlib"]
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_cloud_service_processes_runs_across_instances(tmp_path) -> None:
    api_service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
        embedded_worker_enabled=False,
    )
    upload = api_service.save_upload(
        filename="sales.csv",
        content_type="text/csv",
        payload=b"month,value\n1,10\n2,20\n",
    )
    run = api_service.create_run(
        RemoteTaskRequest(task="分析这个 CSV 并生成趋势图", attachments=[upload.upload_id])
    )

    worker_service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
        embedded_worker_enabled=False,
    )
    processed = await worker_service.process_next_queued_run()

    assert processed is True
    refreshed = api_service.get_run(run.run_id)
    assert refreshed.status == "success"
    artifacts = api_service.list_artifacts(run.run_id)
    assert len(artifacts) == 2
    assert api_service.get_artifact_path(artifacts[0].artifact_id).exists()


def test_cloud_service_recovers_stale_claimed_runs(tmp_path) -> None:
    service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
        embedded_worker_enabled=False,
        queue_claim_timeout_seconds=30,
    )
    upload = service.save_upload(
        filename="sales.csv",
        content_type="text/csv",
        payload=b"month,value\n1,10\n2,20\n",
    )
    run = service.create_run(
        RemoteTaskRequest(task="分析这个 CSV", attachments=[upload.upload_id])
    )
    claim_path = service._claim_next_ticket()
    assert claim_path is not None
    claim_payload = service._read_ticket_payload(claim_path)
    claim_payload["claimed_at"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    service._write_ticket_payload(claim_path, claim_payload)
    run_record = service.get_run(run.run_id)
    run_record.status = "running"
    service._persist_run(run_record)

    recovered = service.recover_stale_claims(now=datetime.now(UTC))

    assert recovered == [run.run_id]
    assert service._queue_ticket_path(run.run_id).exists()
    assert not service._queue_ticket_path(run.run_id, claimed=True).exists()
    refreshed = service.get_run(run.run_id)
    assert refreshed.status == "queued"
    assert refreshed.detail == "Run requeued after stale claim recovery."


def test_cloud_service_drops_stale_claim_for_terminal_run(tmp_path) -> None:
    service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
        embedded_worker_enabled=False,
        queue_claim_timeout_seconds=30,
    )
    upload = service.save_upload(
        filename="sales.csv",
        content_type="text/csv",
        payload=b"month,value\n1,10\n2,20\n",
    )
    run = service.create_run(
        RemoteTaskRequest(task="分析这个 CSV", attachments=[upload.upload_id])
    )
    claim_path = service._claim_next_ticket()
    assert claim_path is not None
    claim_payload = service._read_ticket_payload(claim_path)
    claim_payload["claimed_at"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    service._write_ticket_payload(claim_path, claim_payload)
    run_record = service.get_run(run.run_id)
    run_record.status = "success"
    service._persist_run(run_record)

    recovered = service.recover_stale_claims(now=datetime.now(UTC))

    assert recovered == []
    assert not service._queue_ticket_path(run.run_id, claimed=True).exists()
    assert not service._queue_ticket_path(run.run_id).exists()


def test_cloud_service_returns_failed_run_for_unsupported_task(tmp_path) -> None:
    service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
        embedded_worker_enabled=False,
    )

    run = service.create_run(
        RemoteTaskRequest(task="帮我联网搜索最新 AI 新闻", attachments=[])
    )

    assert run.status == "failed"
    assert run.error_code == "unsupported_task"
    assert run.route_plan.selection_reason == "no_match"
    assert run.route_plan.selected_tools == []
    assert "missing capabilities [web_research]" in run.detail


def test_cloud_service_exposes_registry_and_telemetry(tmp_path) -> None:
    service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
        embedded_worker_enabled=False,
    )

    tools = service.search_tools(capability="data_analysis")
    assert {tool.tool_id for tool in tools} >= {"pandas", "openpyxl"}

    manifest = service.get_tool_manifest("pandas", "0.1.0")
    assert manifest.image == "moe-tool-pandas"

    event = service.record_connector_event(
        TelemetryEvent(
            event_type="task.execute",
            host_client="openclaw",
            status="success",
            run_id="run-1",
            tool_id="pandas",
            tool_version="0.1.0",
            duration_ms=120,
            platform="macOS",
        )
    )
    assert event.host_client == "openclaw"
    logged_events = service.list_connector_events()
    assert logged_events[-1]["tool_id"] == "pandas"
