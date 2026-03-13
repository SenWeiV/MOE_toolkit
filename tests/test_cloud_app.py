from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from moe_toolkit.cloud.app import create_app
from moe_toolkit.cloud.executors import DockerExecutor
from moe_toolkit.cloud.settings import CloudSettings


def test_health_without_auth_returns_none() -> None:
    app = create_app(CloudSettings(api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.get("/v1/service/health")

        assert response.status_code == 200
        payload = response.json()
        assert payload["healthy"] is True
        assert payload["authenticated"] is None


def test_health_with_valid_auth_returns_true() -> None:
    app = create_app(CloudSettings(api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.get(
            "/v1/service/health",
            headers={"Authorization": "Bearer alpha-key"},
        )

        assert response.status_code == 200
        assert response.json()["authenticated"] is True


def test_health_with_invalid_auth_returns_false() -> None:
    app = create_app(CloudSettings(api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.get(
            "/v1/service/health",
            headers={"Authorization": "Bearer wrong-key"},
        )

        assert response.status_code == 200
        assert response.json()["authenticated"] is False


def test_beta_install_page_and_release_endpoints(tmp_path) -> None:
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True)
    archive_path = releases_dir / "moeskills-macos.tar.gz"
    archive_path.write_bytes(b"fake archive")

    app = create_app(
        CloudSettings(
            storage_root=tmp_path,
            public_base_url="http://example.test:8080",
            api_keys_raw="alpha-key",
        )
    )
    with TestClient(app) as client:
        beta_response = client.get("/beta")
        install_response = client.get("/install.sh")
        release_response = client.get("/releases/moeskills-macos.tar.gz")
        legacy_release_response = client.get("/releases/moe-connector-macos.tar.gz")

        assert beta_response.status_code == 200
        assert "MOE Toolkit Beta" in beta_response.text
        assert "curl -fsSL http://example.test:8080/install.sh" in beta_response.text
        assert "moeskills run --task" in beta_response.text

        assert install_response.status_code == 200
        assert 'ARCHIVE_URL="http://example.test:8080/releases/moeskills-macos.tar.gz"' in install_response.text
        assert 'LC_ALL=C tar -xzf "${ARCHIVE_PATH}" -C "${TMP_DIR}"' in install_response.text
        assert 'bash "${TMP_DIR}/moeskills-release/install.sh" "$@"' in install_response.text

        assert release_response.status_code == 200
        assert release_response.content == b"fake archive"
        assert legacy_release_response.status_code == 200
        assert legacy_release_response.content == b"fake archive"
        head_response = client.head("/releases/moe-connector-macos.tar.gz")
        assert head_response.status_code == 200


def test_release_archive_returns_404_when_missing(tmp_path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.get("/releases/moeskills-macos.tar.gz")

    assert response.status_code == 404


def test_upload_execute_and_fetch_artifacts(tmp_path) -> None:
    app = create_app(
        CloudSettings(
            api_keys_raw="alpha-key",
            storage_root=tmp_path,
            api_port=8080,
            public_base_url="http://127.0.0.1:8080",
            queue_poll_interval_seconds=0.01,
        )
    )
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer alpha-key"}

        upload_response = client.post(
            "/v1/files/upload",
            files={"file": ("sales.csv", b"month,value\n1,10\n2,20\n3,30\n", "text/csv")},
            headers=headers,
        )
        assert upload_response.status_code == 200
        upload_id = upload_response.json()["upload_id"]

        task_response = client.post(
            "/v1/tasks/execute",
            json={
                "task": "分析这个 CSV 并生成趋势图",
                "attachments": [upload_id],
                "session_id": "session-1",
                "output_preferences": {},
            },
            headers=headers,
        )
        assert task_response.status_code == 200
        run_id = task_response.json()["run_id"]
        assert task_response.json()["status"] == "queued"

        run_payload = {}
        for _ in range(30):
            run_response = client.get(f"/v1/runs/{run_id}", headers=headers)
            assert run_response.status_code == 200
            run_payload = run_response.json()
            if run_payload["status"] == "success":
                break
        assert run_payload["status"] == "success"
        assert "visualization" in run_payload["route_plan"]["capabilities"]
        assert run_payload["route_plan"]["selected_tools"] == ["pandas", "matplotlib"]

        artifacts_response = client.get(f"/v1/runs/{run_id}/artifacts", headers=headers)
        assert artifacts_response.status_code == 200
        artifacts = artifacts_response.json()
        assert len(artifacts) == 2

        download_response = client.get(
            artifacts[0]["download_url"].replace("http://127.0.0.1:8080", ""),
            headers=headers,
        )
        assert download_response.status_code == 200
        assert download_response.content


def test_upload_execute_and_fetch_artifacts_with_docker_backend(tmp_path) -> None:
    commands: list[list[str]] = []

    async def fake_runner(command: list[str]) -> None:
        commands.append(command)
        run_root = Path(command[command.index("-v") + 1].split(":", 1)[0])
        artifacts_dir = run_root / "artifacts"
        image = command[-1]
        if image == "moe-tool-pandas":
            (artifacts_dir / "01-sales-summary.json").write_text(
                '{"source":"01-sales.csv","rows":3}\n',
                encoding="utf-8",
            )
        elif image == "moe-tool-matplotlib":
            (artifacts_dir / "01-sales-chart.svg").write_text(
                "<svg></svg>\n",
                encoding="utf-8",
            )

    app = create_app(
        CloudSettings(
            api_keys_raw="alpha-key",
            storage_root=tmp_path,
            api_port=8080,
            public_base_url="http://127.0.0.1:8080",
            execution_backend="docker",
            docker_binary="docker-test",
            docker_network_mode="bridge",
            queue_poll_interval_seconds=0.01,
        ),
        executor=DockerExecutor(
            docker_binary="docker-test",
            network_mode="bridge",
            runner=fake_runner,
        ),
    )
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer alpha-key"}

        upload_response = client.post(
            "/v1/files/upload",
            files={"file": ("sales.csv", b"month,value\n1,10\n2,20\n3,30\n", "text/csv")},
            headers=headers,
        )
        assert upload_response.status_code == 200
        upload_id = upload_response.json()["upload_id"]

        task_response = client.post(
            "/v1/tasks/execute",
            json={
                "task": "分析这个 CSV 并生成趋势图",
                "attachments": [upload_id],
                "session_id": "session-1",
                "output_preferences": {},
            },
            headers=headers,
        )
        assert task_response.status_code == 200
        run_id = task_response.json()["run_id"]
        run_payload = {}
        for _ in range(30):
            run_response = client.get(f"/v1/runs/{run_id}", headers=headers)
            assert run_response.status_code == 200
            run_payload = run_response.json()
            if run_payload["status"] == "success":
                break

        assert run_payload["status"] == "success"
        artifacts_response = client.get(f"/v1/runs/{run_id}/artifacts", headers=headers)
        assert artifacts_response.status_code == 200
        artifacts = artifacts_response.json()
        assert len(artifacts) == 2
        assert commands == [
            [
                "docker-test",
                "run",
                "--rm",
                "--network",
                "bridge",
                "-v",
                f"{tmp_path / 'runs' / run_id}:/work",
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
                f"{tmp_path / 'runs' / run_id}:/work",
                "-w",
                "/work",
                "moe-tool-matplotlib",
            ],
        ]


def test_registry_and_telemetry_endpoints(tmp_path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer alpha-key"}

        search_response = client.get(
            "/v1/registry/tools/search?capability=data_analysis&enabled=true",
            headers=headers,
        )
        assert search_response.status_code == 200
        tool_ids = {item["tool_id"] for item in search_response.json()}
        assert "pandas" in tool_ids

        tool_response = client.get("/v1/registry/tools/pandas", headers=headers)
        assert tool_response.status_code == 200
        assert tool_response.json()["tool_id"] == "pandas"

        manifest_response = client.get(
            "/v1/registry/manifests/pandas/0.1.0",
            headers=headers,
        )
        assert manifest_response.status_code == 200
        assert manifest_response.json()["image"] == "moe-tool-pandas"

        telemetry_response = client.post(
            "/v1/telemetry/connector-events",
            json={
                "event_type": "doctor",
                "host_client": "codex-cli",
                "status": "success",
                "platform": "macOS",
            },
            headers=headers,
        )
        assert telemetry_response.status_code == 200
        assert telemetry_response.json()["event_type"] == "doctor"

        stable_telemetry_response = client.post(
            "/v1/telemetry/events",
            json={
                "event_type": "run",
                "host_client": "cli",
                "status": "success",
                "platform": "macOS",
            },
            headers=headers,
        )
        assert stable_telemetry_response.status_code == 200
        assert stable_telemetry_response.json()["host_client"] == "cli"


def test_execute_task_returns_failed_no_match_for_unsupported_request(tmp_path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks/execute",
            json={
                "task": "帮我联网搜索最新 AI 新闻",
                "attachments": [],
                "session_id": "session-1",
                "output_preferences": {},
            },
            headers={"Authorization": "Bearer alpha-key"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "failed"
        assert payload["route_plan"]["selection_reason"] == "no_match"
        assert payload["route_plan"]["selected_tools"] == []


def test_xlsx_request_routes_to_openpyxl_and_returns_spreadsheet(tmp_path) -> None:
    app = create_app(
        CloudSettings(
            api_keys_raw="alpha-key",
            storage_root=tmp_path,
            api_port=8080,
            public_base_url="http://127.0.0.1:8080",
            queue_poll_interval_seconds=0.01,
        )
    )
    workbook_path = tmp_path / "sales.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["month", "value"])
    sheet.append([1, 10])
    sheet.append([2, 20])
    workbook.save(workbook_path)

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer alpha-key"}
        with workbook_path.open("rb") as handle:
            upload_response = client.post(
                "/v1/files/upload",
                files={"file": ("sales.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                headers=headers,
            )
        assert upload_response.status_code == 200
        upload_id = upload_response.json()["upload_id"]

        task_response = client.post(
            "/v1/tasks/execute",
            json={
                "task": "读取这个 Excel 并生成 Excel 报表",
                "attachments": [upload_id],
                "session_id": "session-1",
                "output_preferences": {},
            },
            headers=headers,
        )
        assert task_response.status_code == 200
        assert task_response.json()["route_plan"]["selected_tools"] == ["openpyxl"]
        run_id = task_response.json()["run_id"]

        run_payload = {}
        for _ in range(30):
            run_response = client.get(f"/v1/runs/{run_id}", headers=headers)
            assert run_response.status_code == 200
            run_payload = run_response.json()
            if run_payload["status"] == "success":
                break
        assert run_payload["status"] == "success"

        artifacts_response = client.get(f"/v1/runs/{run_id}/artifacts", headers=headers)
        assert artifacts_response.status_code == 200
        artifact_names = {item["filename"] for item in artifacts_response.json()}
        assert "01-sales-summary.json" in artifact_names
        assert "01-sales-report.xlsx" in artifact_names


def test_upload_rejects_unsupported_file_type(tmp_path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/files/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            headers={"Authorization": "Bearer alpha-key"},
        )

        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]


def test_upload_requires_api_key(tmp_path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/files/upload",
            files={"file": ("sales.csv", b"month,value\n1,10\n", "text/csv")},
        )

        assert response.status_code == 401


def test_execute_task_returns_404_for_unknown_upload(tmp_path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks/execute",
            json={
                "task": "分析这个 CSV",
                "attachments": ["missing-upload"],
                "session_id": "session-1",
                "output_preferences": {},
            },
            headers={"Authorization": "Bearer alpha-key"},
        )

        assert response.status_code == 404
        assert "Unknown upload_id" in response.json()["detail"]


def test_run_and_artifact_endpoints_return_404_for_unknown_ids(tmp_path) -> None:
    app = create_app(
        CloudSettings(
            storage_root=tmp_path,
            api_keys_raw="alpha-key",
            embedded_worker_enabled=False,
        )
    )
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer alpha-key"}

        run_response = client.get("/v1/runs/missing-run", headers=headers)
        artifacts_response = client.get("/v1/runs/missing-run/artifacts", headers=headers)
        download_response = client.get(
            "/v1/artifacts/missing-artifact/download",
            headers=headers,
        )
        health_response = client.get("/v1/service/health", headers=headers)

        assert run_response.status_code == 404
        assert artifacts_response.status_code == 404
        assert download_response.status_code == 404
        assert health_response.status_code == 200
        assert health_response.json()["components"][2]["detail"] == "External worker expected"
