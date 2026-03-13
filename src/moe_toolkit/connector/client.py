"""HTTP client for talking to the MOE cloud API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from moe_toolkit.schemas.common import (
    ArtifactRef,
    ConnectorConfig,
    HealthResponse,
    RemoteTaskRequest,
    RunRecord,
    TaskAccepted,
    TelemetryEvent,
    ToolManifest,
    ToolSummary,
    UploadRef,
)


class CloudClient:
    """Small wrapper around httpx for connector operations."""

    def __init__(
        self,
        config: ConnectorConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._headers: dict[str, str] = {}
        if self._config.api_key:
            self._headers["Authorization"] = f"Bearer {self._config.api_key}"

    def _resolve_download_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return url
        parsed = urlparse(url)
        resolved_path = parsed.path or "/"
        if parsed.query:
            resolved_path = f"{resolved_path}?{parsed.query}"
        return resolved_path

    async def get_health(self) -> HealthResponse:
        """Fetches the cloud health endpoint using the configured API key."""

        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get("/v1/service/health", headers=self._headers)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        return HealthResponse.model_validate(payload)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
    ) -> httpx.Response:
        """Executes a generic authenticated request against the cloud API."""

        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.request(
                method.upper(),
                path,
                json=json_body,
                headers=self._headers,
            )
        return response

    async def upload_file(self, source: Path) -> UploadRef:
        """Uploads a local file to the cloud service."""

        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            with source.open("rb") as handle:
                response = await client.post(
                    "/v1/files/upload",
                    files={"file": (source.name, handle, "application/octet-stream")},
                    headers=self._headers,
                )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        return UploadRef.model_validate(payload)

    async def execute_task(
        self,
        task: str,
        attachments: list[str],
        session_id: str | None = None,
    ) -> TaskAccepted:
        """Creates a remote task and returns the accepted run."""

        request = RemoteTaskRequest(
            task=task,
            attachments=attachments,
            session_id=session_id,
        )
        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(
                "/v1/tasks/execute",
                json=request.model_dump(mode="json"),
                headers=self._headers,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        return TaskAccepted.model_validate(payload)

    async def get_run(self, run_id: str) -> RunRecord:
        """Fetches a run by ID."""

        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get(f"/v1/runs/{run_id}", headers=self._headers)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        return RunRecord.model_validate(payload)

    async def wait_for_run(self, run_id: str) -> RunRecord:
        """Polls until the run reaches a terminal state."""

        while True:
            run = await self.get_run(run_id)
            if run.status in {"success", "failed"}:
                return run
            await asyncio.sleep(self._config.run_poll_interval_seconds)

    async def get_artifacts(self, run_id: str) -> list[ArtifactRef]:
        """Lists artifacts for a completed run."""

        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get(
                f"/v1/runs/{run_id}/artifacts",
                headers=self._headers,
            )
            response.raise_for_status()
            payload: list[dict[str, Any]] = response.json()
        return [ArtifactRef.model_validate(item) for item in payload]

    async def search_tools(
        self,
        *,
        capability: str | None = None,
        input_type: str | None = None,
        enabled: bool | None = None,
    ) -> list[ToolSummary]:
        """Searches curated tools through the public registry endpoint."""

        query: list[str] = []
        if capability is not None:
            query.append(f"capability={capability}")
        if input_type is not None:
            query.append(f"input_type={input_type}")
        if enabled is not None:
            query.append(f"enabled={str(enabled).lower()}")
        path = "/v1/registry/tools/search"
        if query:
            path = f"{path}?{'&'.join(query)}"
        response = await self.request("GET", path)
        response.raise_for_status()
        payload: list[dict[str, Any]] = response.json()
        return [ToolSummary.model_validate(item) for item in payload]

    async def get_tool(self, tool_id: str) -> ToolSummary:
        """Loads a single curated tool summary."""

        response = await self.request("GET", f"/v1/registry/tools/{tool_id}")
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return ToolSummary.model_validate(payload)

    async def get_manifest(self, tool_id: str, version: str) -> ToolManifest:
        """Loads a full curated tool manifest."""

        response = await self.request("GET", f"/v1/registry/manifests/{tool_id}/{version}")
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return ToolManifest.model_validate(payload)

    async def record_telemetry(self, event: TelemetryEvent) -> TelemetryEvent:
        """Records a connector telemetry event through the stable endpoint."""

        response = await self.request(
            "POST",
            "/v1/telemetry/events",
            json_body=event.model_dump(mode="json"),
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return TelemetryEvent.model_validate(payload)

    async def download_artifact(self, artifact: ArtifactRef, output_dir: Path) -> Path:
        """Downloads an artifact to the connector output directory."""

        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / f"{artifact.run_id}-{artifact.filename}"
        async with httpx.AsyncClient(
            base_url=self._config.server_url,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get(
                self._resolve_download_url(artifact.download_url),
                headers=self._headers,
            )
            response.raise_for_status()
        destination.write_bytes(response.content)
        return destination
