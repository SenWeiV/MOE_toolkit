from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from moe_toolkit.cloud import cleanup as cleanup_module
from moe_toolkit.cloud import cleanup_main, main as cloud_main, worker_main
from moe_toolkit.cloud.settings import CloudSettings


class StopLoop(Exception):
    pass


def test_cloud_main_runs_uvicorn_with_configured_settings(monkeypatch, tmp_path: Path) -> None:
    settings = CloudSettings(
        api_host="127.0.0.1",
        api_port=9999,
        storage_root=tmp_path,
        api_keys_raw="alpha-key",
    )
    sentinel_app = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(cloud_main, "CloudSettings", lambda: settings)
    monkeypatch.setattr(cloud_main, "create_app", lambda current: sentinel_app if current == settings else None)

    def fake_run(app, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(cloud_main.uvicorn, "run", fake_run)

    cloud_main.main()

    assert captured == {
        "app": sentinel_app,
        "host": "127.0.0.1",
        "port": 9999,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend", "expected_executor_type"),
    [
        ("inline", "InlineExecutor"),
        ("docker", "DockerExecutor"),
    ],
)
async def test_worker_main_run_worker_constructs_expected_service(
    monkeypatch,
    tmp_path: Path,
    backend: str,
    expected_executor_type: str,
) -> None:
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(
            self,
            storage_root: Path,
            base_url: str,
            executor,
            *,
            embedded_worker_enabled: bool,
            queue_poll_interval_seconds: float,
            queue_claim_timeout_seconds: int,
        ) -> None:
            captured["storage_root"] = storage_root
            captured["base_url"] = base_url
            captured["executor_type"] = type(executor).__name__
            if expected_executor_type == "DockerExecutor":
                captured["docker_binary"] = executor.docker_binary
                captured["docker_storage_root"] = executor.storage_root
                captured["docker_host_storage_root"] = executor.host_storage_root
            captured["embedded_worker_enabled"] = embedded_worker_enabled
            captured["queue_poll_interval_seconds"] = queue_poll_interval_seconds
            captured["queue_claim_timeout_seconds"] = queue_claim_timeout_seconds

        async def process_next_queued_run(self) -> bool:
            return False

    async def fake_sleep(seconds: float) -> None:
        captured["sleep_seconds"] = seconds
        raise StopLoop()

    monkeypatch.setattr(worker_main, "CloudService", FakeService)
    monkeypatch.setattr(worker_main.asyncio, "sleep", fake_sleep)

    settings = CloudSettings(
        storage_root=tmp_path,
        public_base_url="http://testserver",
        execution_backend=backend,
        docker_binary="/usr/bin/docker",
        docker_host_storage_root=tmp_path / "host-root",
        queue_poll_interval_seconds=0.05,
    )

    with pytest.raises(StopLoop):
        await worker_main.run_worker(settings)

    assert captured["storage_root"] == tmp_path
    assert captured["base_url"] == "http://testserver"
    assert captured["executor_type"] == expected_executor_type
    assert captured["embedded_worker_enabled"] is False
    assert captured["queue_poll_interval_seconds"] == 0.05
    assert captured["queue_claim_timeout_seconds"] == 300
    assert captured["sleep_seconds"] == 0.05
    if backend == "docker":
        assert captured["docker_binary"] == "/usr/bin/docker"
        assert captured["docker_storage_root"] == tmp_path
        assert captured["docker_host_storage_root"] == tmp_path / "host-root"


def test_worker_main_main_invokes_asyncio_run(monkeypatch, tmp_path: Path) -> None:
    settings = CloudSettings(storage_root=tmp_path)
    captured: dict[str, object] = {}

    async def fake_run_worker(current_settings: CloudSettings) -> None:
        captured["settings"] = current_settings

    def fake_asyncio_run(coro) -> None:
        captured["coroutine_name"] = coro.cr_code.co_name
        coro.close()

    monkeypatch.setattr(worker_main, "CloudSettings", lambda: settings)
    monkeypatch.setattr(worker_main, "run_worker", fake_run_worker)
    monkeypatch.setattr(worker_main.asyncio, "run", fake_asyncio_run)

    worker_main.main()

    assert captured["coroutine_name"] == "fake_run_worker"


def test_run_cleanup_cycle_logs_cleanup_report(monkeypatch, tmp_path: Path) -> None:
    captured: list[str] = []

    class FakeLogger:
        def info(self, message: str, *args) -> None:
            captured.append(message % args if args else message)

    monkeypatch.setattr(
        cleanup_main,
        "cleanup_expired_uploads",
        lambda storage_root: cleanup_module.CleanupReport(
            scanned_upload_dirs=3,
            removed_upload_dirs=1,
            skipped_upload_dirs=2,
        ),
    )

    cleanup_main.run_cleanup_cycle(
        CloudSettings(storage_root=tmp_path),
        FakeLogger(),
    )

    assert captured == [
        "Cleanup cycle completed: scanned_upload_dirs=3 removed_upload_dirs=1 skipped_upload_dirs=2"
    ]


def test_cleanup_main_main_runs_single_cycle_before_stop(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = CloudSettings(storage_root=tmp_path, cleanup_interval_seconds=15)
    captured: dict[str, object] = {}

    def fake_run_cleanup_cycle(current_settings: CloudSettings, logger: logging.Logger) -> None:
        captured["settings"] = current_settings
        captured["logger"] = logger
        raise StopLoop()

    monkeypatch.setattr(cleanup_main, "CloudSettings", lambda: settings)
    monkeypatch.setattr(cleanup_main, "run_cleanup_cycle", fake_run_cleanup_cycle)

    with caplog.at_level(logging.INFO), pytest.raises(StopLoop):
        cleanup_main.main()

    assert "MOE cleanup job started for storage_root=" in caplog.text
    assert captured["settings"] == settings
    assert isinstance(captured["logger"], logging.Logger)
