"""Core services used by the MOE cloud API."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from moe_toolkit.cloud.executors import (
    ExecutionBackend,
    detect_media_type,
    prepare_run_workspace,
)
from moe_toolkit.cloud.registry import CuratedRegistry, RouteDecision, RuleBasedCuratedRouter
from moe_toolkit.schemas.common import (
    ArtifactRef,
    RemoteTaskRequest,
    RunRecord,
    TelemetryEvent,
    ToolManifest,
    ToolSummary,
    UploadRef,
)

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".xlsx", ".zip"}


@dataclass(slots=True)
class CloudState:
    """In-memory service state used by the first implementation slice."""

    uploads: dict[str, UploadRef] = field(default_factory=dict)
    upload_paths: dict[str, Path] = field(default_factory=dict)
    runs: dict[str, RunRecord] = field(default_factory=dict)
    artifacts: dict[str, ArtifactRef] = field(default_factory=dict)
    artifact_paths: dict[str, Path] = field(default_factory=dict)
    requests: dict[str, RemoteTaskRequest] = field(default_factory=dict)
    run_roots: dict[str, Path] = field(default_factory=dict)


class CloudService:
    """Implements upload handling and queued task execution."""

    def __init__(
        self,
        storage_root: Path,
        base_url: str,
        executor: ExecutionBackend,
        registry: CuratedRegistry | None = None,
        *,
        embedded_worker_enabled: bool = True,
        queue_poll_interval_seconds: float = 0.1,
        queue_claim_timeout_seconds: int = 300,
    ) -> None:
        self.storage_root = storage_root
        self.upload_root = storage_root / "uploads"
        self.artifact_root = storage_root / "artifacts"
        self.run_root = storage_root / "runs"
        self.queue_pending_root = storage_root / "queue" / "pending"
        self.queue_claimed_root = storage_root / "queue" / "claimed"
        self.telemetry_root = storage_root / "telemetry"
        self.route_log_path = self.telemetry_root / "route_decisions.jsonl"
        self.connector_event_log_path = self.telemetry_root / "connector_events.jsonl"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.queue_pending_root.mkdir(parents=True, exist_ok=True)
        self.queue_claimed_root.mkdir(parents=True, exist_ok=True)
        self.telemetry_root.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")
        self.state = CloudState()
        self.executor = executor
        self.registry = registry or CuratedRegistry()
        self.router = RuleBasedCuratedRouter(self.registry)
        self.embedded_worker_enabled = embedded_worker_enabled
        self.queue_poll_interval_seconds = queue_poll_interval_seconds
        self.queue_claim_timeout_seconds = queue_claim_timeout_seconds
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Starts the in-process queue worker."""

        if not self.embedded_worker_enabled or self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Stops the in-process queue worker."""

        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        finally:
            self._worker_task = None

    def save_upload(
        self,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> UploadRef:
        """Stores an uploaded file after validating its type and size."""

        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported file type: {suffix or '<none>'}")

        upload_id = uuid.uuid4().hex
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        target_dir = self.upload_root / upload_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_bytes(payload)

        ref = UploadRef(
            upload_id=upload_id,
            filename=filename,
            size_bytes=len(payload),
            content_type=content_type or "application/octet-stream",
            expires_at=expires_at,
        )
        self.state.uploads[upload_id] = ref
        self.state.upload_paths[upload_id] = target_path
        (target_dir / "metadata.json").write_text(
            ref.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return ref

    def create_run(self, request: RemoteTaskRequest) -> RunRecord:
        """Creates a run and enqueues it for background processing."""

        uploads: list[UploadRef] = []
        for upload_id in request.attachments:
            upload, _ = self._load_upload(upload_id)
            uploads.append(upload)

        run_id = uuid.uuid4().hex
        route_decision = self.router.build_route(task=request.task, uploads=uploads)
        run = RunRecord(
            run_id=run_id,
            session_id=request.session_id,
            status="queued" if route_decision.route_plan.selected_tools else "failed",
            task=request.task,
            route_plan=route_decision.route_plan,
            error_code=None if route_decision.route_plan.selected_tools else "unsupported_task",
            detail=(
                "Run accepted"
                if route_decision.route_plan.selected_tools
                else route_decision.route_plan.explanation
            ),
        )
        self.state.runs[run_id] = run
        self.state.requests[run_id] = request
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._persist_run(run)
        self._persist_request(run_id, request)
        self._record_route_decision(
            run_id=run_id,
            task=request.task,
            route_decision=route_decision,
        )
        if route_decision.route_plan.selected_tools:
            self._enqueue_run(run_id)
        return run

    def get_run(self, run_id: str) -> RunRecord:
        """Returns an existing run or raises KeyError."""

        return self._load_run(run_id)

    def search_tools(
        self,
        *,
        capability: str | None = None,
        input_type: str | None = None,
        enabled: bool | None = None,
    ) -> list[ToolSummary]:
        """Returns curated tools with optional filters."""

        return self.registry.search(capability=capability, input_type=input_type, enabled=enabled)

    def get_tool_summary(self, tool_id: str) -> ToolSummary:
        """Returns a single curated tool summary."""

        return self.registry.get_summary(tool_id)

    def get_tool_manifest(self, tool_id: str, version: str) -> ToolManifest:
        """Returns a full curated manifest by tool/version."""

        return self.registry.get_manifest(tool_id, version)

    def list_artifacts(self, run_id: str) -> list[ArtifactRef]:
        """Returns artifacts associated with a run."""

        run = self.get_run(run_id)
        return [self._load_artifact(artifact_id) for artifact_id in run.artifact_ids]

    def get_artifact_path(self, artifact_id: str) -> Path:
        """Returns the on-disk path for an artifact."""

        if artifact_id not in self.state.artifact_paths:
            self._load_artifact(artifact_id)
        return self.state.artifact_paths[artifact_id]

    def record_connector_event(self, event: TelemetryEvent) -> TelemetryEvent:
        """Persists a connector telemetry event."""

        self._append_jsonl(self.connector_event_log_path, event.model_dump(mode="json"))
        return event

    def list_route_decisions(self) -> list[dict[str, Any]]:
        """Returns persisted route decisions for tests and debugging."""

        return self._read_jsonl(self.route_log_path)

    def list_connector_events(self) -> list[dict[str, Any]]:
        """Returns persisted connector telemetry events for tests and debugging."""

        return self._read_jsonl(self.connector_event_log_path)

    async def _worker_loop(self) -> None:
        """Consumes queued runs and processes them sequentially."""

        while True:
            processed = await self.process_next_queued_run()
            if not processed:
                await asyncio.sleep(self.queue_poll_interval_seconds)

    async def process_next_queued_run(self) -> bool:
        """Claims and processes a queued run if one exists."""

        self.recover_stale_claims()
        claim_path = self._claim_next_ticket()
        if claim_path is None:
            return False

        run_id = claim_path.stem
        request = self._load_request(run_id)
        try:
            await self._process_run(run_id, request)
        finally:
            if claim_path.exists():
                claim_path.unlink()
        return True

    def recover_stale_claims(self, *, now: datetime | None = None) -> list[str]:
        """Requeues stale claimed tickets so runs do not get stuck forever."""

        current_time = now or datetime.now(UTC)
        recovered_run_ids: list[str] = []
        for claim_path in sorted(self.queue_claimed_root.glob("*.json")):
            payload = self._read_ticket_payload(claim_path)
            claimed_at_raw = payload.get("claimed_at")
            if claimed_at_raw is None:
                stale = True
            else:
                claimed_at = datetime.fromisoformat(claimed_at_raw)
                stale = (current_time - claimed_at).total_seconds() >= self.queue_claim_timeout_seconds
            if not stale:
                continue

            run_id = claim_path.stem
            run = self._load_run(run_id)
            if run.status in {"success", "failed"}:
                claim_path.unlink(missing_ok=True)
                continue

            pending_path = self._queue_ticket_path(run_id)
            payload["recovered_at"] = current_time.isoformat()
            payload.pop("claimed_at", None)
            pending_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            claim_path.unlink(missing_ok=True)
            run.status = "queued"
            run.detail = "Run requeued after stale claim recovery."
            run.updated_at = current_time
            self._persist_run(run)
            recovered_run_ids.append(run_id)
        return recovered_run_ids

    async def _process_run(self, run_id: str, request: RemoteTaskRequest) -> None:
        run = self._load_run(run_id)
        run.status = "running"
        run.updated_at = datetime.now(UTC)
        self._persist_run(run)
        try:
            context = prepare_run_workspace(
                storage_root=self.storage_root,
                run_id=run_id,
                request=request,
                upload_paths={
                    upload_id: self._load_upload(upload_id)[1]
                    for upload_id in request.attachments
                },
                route_plan=run.route_plan,
            )
            self.state.run_roots[run_id] = context.run_root
            await self.executor.execute(context)
            self._register_artifacts(run_id, context.artifacts_dir)
            run = self._load_run(run_id)
            run.status = "success"
            run.detail = "Queued processor completed."
        except Exception as exc:  # pragma: no cover - defensive path
            run = self._load_run(run_id)
            run.status = "failed"
            run.error_code = "run_execution_failed"
            run.detail = str(exc)
        finally:
            run.updated_at = datetime.now(UTC)
            self._persist_run(run)

    def _register_artifacts(self, run_id: str, artifacts_dir: Path) -> None:
        for artifact_path in sorted(path for path in artifacts_dir.iterdir() if path.is_file()):
            artifact_id = uuid.uuid4().hex
            ref = ArtifactRef(
                artifact_id=artifact_id,
                run_id=run_id,
                filename=artifact_path.name,
                media_type=detect_media_type(artifact_path),
                size_bytes=artifact_path.stat().st_size,
                download_url=f"{self.base_url}/v1/artifacts/{artifact_id}/download",
            )
            self.state.artifacts[artifact_id] = ref
            self.state.artifact_paths[artifact_id] = artifact_path
            self._persist_artifact(ref, artifact_path)
            run = self._load_run(run_id)
            run.artifact_ids.append(artifact_id)
            self._persist_run(run)

    def _run_dir(self, run_id: str) -> Path:
        return self.run_root / run_id

    def _record_route_decision(
        self,
        *,
        run_id: str,
        task: str,
        route_decision: RouteDecision,
    ) -> None:
        self._append_jsonl(
            self.route_log_path,
            {
                "run_id": run_id,
                "task": task,
                "required_capabilities": route_decision.required_capabilities,
                "input_types": route_decision.input_types,
                "selected_tools": route_decision.route_plan.selected_tools,
                "selected_images": route_decision.route_plan.selected_images,
                "selection_reason": route_decision.route_plan.selection_reason,
                "explanation": route_decision.route_plan.explanation,
                "matches": [
                    match.model_dump(mode="json")
                    for match in route_decision.matches
                ],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def _run_record_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run_record.json"

    def _run_request_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "request.json"

    def _queue_ticket_path(self, run_id: str, *, claimed: bool = False) -> Path:
        root = self.queue_claimed_root if claimed else self.queue_pending_root
        return root / f"{run_id}.json"

    def _artifact_metadata_path(self, artifact_id: str) -> Path:
        return self.artifact_root / f"{artifact_id}.json"

    def _enqueue_run(self, run_id: str) -> None:
        self._write_ticket_payload(
            self._queue_ticket_path(run_id),
            {
                "run_id": run_id,
                "enqueued_at": datetime.now(UTC).isoformat(),
            },
        )

    def _claim_next_ticket(self) -> Path | None:
        pending_paths = sorted(self.queue_pending_root.glob("*.json"))
        for pending_path in pending_paths:
            payload = self._read_ticket_payload(pending_path)
            claim_path = self._queue_ticket_path(pending_path.stem, claimed=True)
            try:
                pending_path.replace(claim_path)
            except FileNotFoundError:
                continue
            payload["claimed_at"] = datetime.now(UTC).isoformat()
            self._write_ticket_payload(claim_path, payload)
            return claim_path
        return None

    @staticmethod
    def _read_ticket_payload(path: Path) -> dict[str, str]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_ticket_payload(path: Path, payload: dict[str, str]) -> None:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records

    def _persist_run(self, run: RunRecord) -> None:
        self.state.runs[run.run_id] = run
        self._run_record_path(run.run_id).write_text(
            run.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    def _persist_request(self, run_id: str, request: RemoteTaskRequest) -> None:
        self.state.requests[run_id] = request
        self._run_request_path(run_id).write_text(
            request.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    def _persist_artifact(self, artifact: ArtifactRef, artifact_path: Path) -> None:
        payload = artifact.model_dump(mode="json")
        payload["path"] = str(artifact_path.relative_to(self.storage_root))
        self._artifact_metadata_path(artifact.artifact_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _load_run(self, run_id: str) -> RunRecord:
        path = self._run_record_path(run_id)
        if not path.exists():
            raise KeyError(run_id)
        run = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        self.state.runs[run_id] = run
        return run

    def _load_request(self, run_id: str) -> RemoteTaskRequest:
        if run_id in self.state.requests:
            return self.state.requests[run_id]
        path = self._run_request_path(run_id)
        if not path.exists():
            raise KeyError(run_id)
        request = RemoteTaskRequest.model_validate_json(path.read_text(encoding="utf-8"))
        self.state.requests[run_id] = request
        return request

    def _load_artifact(self, artifact_id: str) -> ArtifactRef:
        path = self._artifact_metadata_path(artifact_id)
        if not path.exists():
            raise KeyError(artifact_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifact_path = self.storage_root / payload.pop("path")
        artifact = ArtifactRef.model_validate(payload)
        self.state.artifacts[artifact_id] = artifact
        self.state.artifact_paths[artifact_id] = artifact_path
        return artifact

    def _load_upload(self, upload_id: str) -> tuple[UploadRef, Path]:
        if upload_id in self.state.uploads and upload_id in self.state.upload_paths:
            return self.state.uploads[upload_id], self.state.upload_paths[upload_id]

        upload_dir = self.upload_root / upload_id
        metadata_path = upload_dir / "metadata.json"
        if not metadata_path.exists():
            raise KeyError(f"Unknown upload_id: {upload_id}")

        upload = UploadRef.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        upload_path = upload_dir / upload.filename
        if not upload_path.exists():
            raise KeyError(f"Missing upload payload for upload_id: {upload_id}")

        self.state.uploads[upload_id] = upload
        self.state.upload_paths[upload_id] = upload_path
        return upload, upload_path
