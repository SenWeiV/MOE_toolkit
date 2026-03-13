"""FastAPI application for the MOE cloud service."""

from __future__ import annotations

import csv
import secrets
import time
from contextlib import asynccontextmanager
from html import escape
from io import StringIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from moe_toolkit.admin.beta_keys import (
    filename_slug,
    filter_records,
    issue_key,
    list_keys,
    load_records,
    render_email_body,
    render_install_command,
    revoke_key,
)
from moe_toolkit.cloud.admin_ui import build_admin_dashboard, build_admin_login_page
from moe_toolkit.cloud.executors import DockerExecutor, ExecutionBackend, InlineExecutor
from moe_toolkit.cloud.services import CloudService
from moe_toolkit.cloud.security import extract_bearer_token, require_authorization
from moe_toolkit.cloud.settings import CloudSettings
from moe_toolkit.schemas.common import (
    ArtifactRef,
    HealthComponent,
    HealthResponse,
    RemoteTaskRequest,
    RunRecord,
    TaskAccepted,
    TelemetryEvent,
    ToolManifest,
    ToolSummary,
    UploadRef,
)


def resolve_executor(
    settings: CloudSettings,
    executor: ExecutionBackend | None = None,
) -> ExecutionBackend:
    """Resolves the execution backend for the application."""

    if executor is not None:
        return executor
    if settings.execution_backend == "docker":
        return DockerExecutor(
            docker_binary=settings.docker_binary,
            storage_root=settings.storage_root,
            host_storage_root=settings.docker_host_storage_root,
            network_mode=settings.docker_network_mode,
        )
    return InlineExecutor()


def create_app(
    settings: CloudSettings | None = None,
    executor: ExecutionBackend | None = None,
) -> FastAPI:
    """Creates a configured FastAPI app instance."""

    resolved_settings = settings or CloudSettings()
    resolved_executor = resolve_executor(resolved_settings, executor=executor)
    cloud_service = CloudService(
        storage_root=resolved_settings.storage_root,
        base_url=resolved_settings.public_base_url,
        executor=resolved_executor,
        embedded_worker_enabled=resolved_settings.embedded_worker_enabled,
        queue_poll_interval_seconds=resolved_settings.queue_poll_interval_seconds,
        queue_claim_timeout_seconds=resolved_settings.queue_claim_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.cloud_service = cloud_service
        await cloud_service.start()
        try:
            yield
        finally:
            await cloud_service.stop()

    app = FastAPI(
        title="MOE Toolkit Cloud API",
        version=resolved_settings.service_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved_settings.admin_session_secret or "moe-admin-disabled",
        session_cookie="moe_admin_session",
        same_site="lax",
        https_only=False,
        max_age=resolved_settings.admin_session_max_age_seconds,
    )

    login_attempts: dict[str, list[float]] = {}

    def get_settings() -> CloudSettings:
        return app.state.settings

    def get_cloud_service() -> CloudService:
        return app.state.cloud_service

    def get_release_archive_path() -> Path:
        releases_root = resolved_settings.storage_root / "releases"
        primary = releases_root / "moeskills-macos.tar.gz"
        if primary.exists():
            return primary
        return releases_root / "moe-connector-macos.tar.gz"

    def get_api_key_store_path() -> Path:
        return resolved_settings.resolved_api_key_store_path

    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"

    def admin_redirect(
        path: str,
        *,
        message: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        query = {
            key: value
            for key, value in {"message": message, "error": error}.items()
            if value
        }
        location = path
        if query:
            location = f"{path}?{urlencode(query)}"
        response = RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)
        no_store(response)
        return response

    def require_admin_enabled() -> None:
        if not resolved_settings.admin_enabled:
            raise HTTPException(status_code=404, detail="Admin UI is not enabled.")

    def get_client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def prune_login_attempts(client_ip: str) -> list[float]:
        now = time.monotonic()
        window = resolved_settings.admin_login_window_seconds
        active_attempts = [
            attempt
            for attempt in login_attempts.get(client_ip, [])
            if now - attempt <= window
        ]
        if active_attempts:
            login_attempts[client_ip] = active_attempts
        else:
            login_attempts.pop(client_ip, None)
        return active_attempts

    def is_login_rate_limited(client_ip: str) -> bool:
        attempts = prune_login_attempts(client_ip)
        return len(attempts) >= resolved_settings.admin_login_max_attempts

    def record_login_failure(client_ip: str) -> None:
        attempts = prune_login_attempts(client_ip)
        attempts.append(time.monotonic())
        login_attempts[client_ip] = attempts

    def clear_login_failures(client_ip: str) -> None:
        login_attempts.pop(client_ip, None)

    def is_admin_authenticated(request: Request) -> bool:
        return bool(request.session.get("admin_authenticated"))

    def ensure_csrf_token(request: Request) -> str:
        token = request.session.get("admin_csrf_token")
        if not token:
            token = secrets.token_urlsafe(24)
            request.session["admin_csrf_token"] = token
        return token

    def validate_csrf(request: Request, csrf_token: str) -> None:
        expected = request.session.get("admin_csrf_token")
        if not expected or not secrets.compare_digest(expected, csrf_token):
            raise HTTPException(status_code=403, detail="Invalid admin CSRF token.")

    def list_all_key_records() -> list:
        return list_keys(store_path=get_api_key_store_path(), status="all")

    def validate_api_key(
        current_settings: CloudSettings = Depends(get_settings),
        authorization: str | None = Header(default=None),
    ) -> str:
        return require_authorization(current_settings, authorization)

    @app.get("/v1/service/health", response_model=HealthResponse)
    async def service_health(
        current_settings: CloudSettings = Depends(get_settings),
        authorization: str | None = Header(default=None),
    ) -> HealthResponse:
        token = extract_bearer_token(authorization)
        authenticated: bool | None
        if token is None:
            authenticated = None
        else:
            authenticated = token in current_settings.api_keys

        auth_detail = "Bearer token validation enabled"
        if current_settings.persisted_api_keys:
            auth_detail = "Bearer token validation enabled (env + persistent key store)"

        components = [
            HealthComponent(
                name="api",
                healthy=True,
                detail=f"{current_settings.service_name} responding",
            ),
            HealthComponent(
                name="auth",
                healthy=True,
                detail=auth_detail,
            ),
            HealthComponent(
                name="worker",
                healthy=True,
                detail=(
                    "Embedded queue worker enabled"
                    if current_settings.embedded_worker_enabled
                    else "External worker expected"
                ),
            ),
        ]
        return HealthResponse(
            service=current_settings.service_name,
            version=current_settings.service_version,
            healthy=True,
            authenticated=authenticated,
            components=components,
        )

    @app.get("/admin/login", response_class=HTMLResponse)
    async def admin_login_page(request: Request) -> Response:
        require_admin_enabled()
        if is_admin_authenticated(request):
            return admin_redirect("/admin")
        response = HTMLResponse(
            build_admin_login_page(
                message=str(request.query_params.get("message") or ""),
                error=str(request.query_params.get("error") or ""),
            )
        )
        no_store(response)
        return response

    @app.post("/admin/login")
    async def admin_login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> Response:
        require_admin_enabled()
        client_ip = get_client_ip(request)
        if is_login_rate_limited(client_ip):
            response = HTMLResponse(
                build_admin_login_page(error="Too many failed login attempts. Try again later."),
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            no_store(response)
            return response
        username_ok = secrets.compare_digest(username, resolved_settings.admin_username)
        password_ok = secrets.compare_digest(password, resolved_settings.admin_password)
        if not (username_ok and password_ok):
            record_login_failure(client_ip)
            response = HTMLResponse(
                build_admin_login_page(error="Invalid username or password."),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
            no_store(response)
            return response
        clear_login_failures(client_ip)
        request.session.clear()
        request.session["admin_authenticated"] = True
        request.session["admin_username"] = resolved_settings.admin_username
        request.session["admin_csrf_token"] = secrets.token_urlsafe(24)
        return admin_redirect("/admin", message="Signed in successfully.")

    @app.post("/admin/logout")
    async def admin_logout(
        request: Request,
        csrf_token: str = Form(...),
    ) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login", error="Session expired.")
        validate_csrf(request, csrf_token)
        request.session.clear()
        return admin_redirect("/admin/login", message="Signed out.")

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_dashboard(request: Request) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login")
        csrf_token = ensure_csrf_token(request)
        response = HTMLResponse(
            build_admin_dashboard(
                records=list_all_key_records(),
                csrf_token=csrf_token,
                server_url=resolved_settings.public_base_url.rstrip("/"),
                message=str(request.query_params.get("message") or ""),
                error=str(request.query_params.get("error") or ""),
            )
        )
        no_store(response)
        return response

    @app.post("/admin/issue")
    async def admin_issue_key(
        request: Request,
        owner_name: str = Form(...),
        contact: str = Form(""),
        note: str = Form(""),
        host_client: str = Form("codex-cli"),
        csrf_token: str = Form(...),
    ) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login", error="Session expired.")
        try:
            validate_csrf(request, csrf_token)
            record = issue_key(
                store_path=get_api_key_store_path(),
                owner_name=owner_name,
                contact=contact.strip(),
                note=note.strip(),
                host_client=host_client.strip(),
            )
        except ValueError as exc:
            return admin_redirect("/admin", error=str(exc))
        return admin_redirect("/admin", message=f"Issued key for {record.owner_name}.")

    @app.post("/admin/revoke")
    async def admin_revoke_key(
        request: Request,
        key_id: str = Form(...),
        csrf_token: str = Form(...),
    ) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login", error="Session expired.")
        try:
            validate_csrf(request, csrf_token)
            record = revoke_key(store_path=get_api_key_store_path(), key_id=key_id)
        except KeyError as exc:
            return admin_redirect("/admin", error=str(exc))
        return admin_redirect("/admin", message=f"Revoked key for {record.owner_name}.")

    @app.get("/admin/email-template/{key_id}.txt", response_class=PlainTextResponse)
    async def admin_download_email_template(
        request: Request,
        key_id: str,
    ) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login", error="Session expired.")
        for record in load_records(get_api_key_store_path()):
            if record.key_id == key_id:
                response = PlainTextResponse(
                    render_email_body(record, server_url=resolved_settings.public_base_url.rstrip("/"))
                )
                response.headers["Content-Disposition"] = (
                    f'attachment; filename="{record.key_id}-{filename_slug(record.owner_name)}.txt"'
                )
                no_store(response)
                return response
        raise HTTPException(status_code=404, detail="Unknown key_id.")

    @app.get("/admin/install-command/{key_id}", response_class=PlainTextResponse)
    async def admin_install_command(
        request: Request,
        key_id: str,
    ) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login", error="Session expired.")
        for record in load_records(get_api_key_store_path()):
            if record.key_id == key_id:
                response = PlainTextResponse(
                    render_install_command(
                        api_key=record.api_key,
                        server_url=resolved_settings.public_base_url.rstrip("/"),
                        host=record.host_client,
                    )
                )
                no_store(response)
                return response
        raise HTTPException(status_code=404, detail="Unknown key_id.")

    @app.get("/admin/email-manifest.csv", response_class=PlainTextResponse)
    async def admin_email_manifest(
        request: Request,
        status_filter: str = Query("active", alias="status"),
    ) -> Response:
        require_admin_enabled()
        if not is_admin_authenticated(request):
            return admin_redirect("/admin/login", error="Session expired.")
        normalized_status: Literal["active", "revoked", "all"] = (
            status_filter if status_filter in {"active", "revoked", "all"} else "active"
        )
        records = filter_records(
            records=load_records(get_api_key_store_path()),
            status=normalized_status,
        )
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "key_id",
                "owner_name",
                "contact",
                "status",
                "host_client",
                "install_command",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "key_id": record.key_id,
                    "owner_name": record.owner_name,
                    "contact": record.contact,
                    "status": record.status,
                    "host_client": record.host_client,
                    "install_command": render_install_command(
                        api_key=record.api_key,
                        server_url=resolved_settings.public_base_url.rstrip("/"),
                        host=record.host_client,
                    ),
                }
            )
        response = PlainTextResponse(output.getvalue(), media_type="text/csv")
        response.headers["Content-Disposition"] = 'attachment; filename="moe-beta-email-manifest.csv"'
        no_store(response)
        return response

    @app.get("/beta", response_class=HTMLResponse)
    async def beta_install_page(
        current_settings: CloudSettings = Depends(get_settings),
    ) -> HTMLResponse:
        base_url = current_settings.public_base_url.rstrip("/")
        codex_install_command = (
            f"curl -fsSL {base_url}/install.sh | "
            f"bash -s -- --server-url {base_url} --api-key &lt;YOUR_KEY&gt; --host codex-cli"
        )
        claude_install_command = (
            f"curl -fsSL {base_url}/install.sh | "
            f"bash -s -- --server-url {base_url} --api-key &lt;YOUR_KEY&gt; --host claude-code"
        )
        openclaw_install_command = (
            f"curl -fsSL {base_url}/install.sh | "
            f"bash -s -- --server-url {base_url} --api-key &lt;YOUR_KEY&gt; --host openclaw"
        )
        archive_url = f"{base_url}/releases/moeskills-macos.tar.gz"
        html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>MOE Toolkit Beta Install</title>
    <style>
      body {{
        font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        max-width: 860px;
        margin: 0 auto;
        padding: 48px 24px 72px;
        background: #f5f7fb;
        color: #0f172a;
      }}
      main {{
        background: white;
        border-radius: 18px;
        padding: 32px;
        box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
      }}
      h1 {{
        margin-top: 0;
        font-size: 2rem;
      }}
      code, pre {{
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      }}
      pre {{
        background: #0f172a;
        color: #e2e8f0;
        padding: 16px;
        border-radius: 12px;
        overflow-x: auto;
      }}
      .muted {{
        color: #475569;
      }}
      .card {{
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        padding: 16px;
        border-radius: 12px;
        margin: 20px 0;
      }}
      ol, ul {{
        line-height: 1.7;
      }}
      a {{
        color: #2563eb;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>MOE Toolkit Beta</h1>
      <p class="muted">
        This page is for invited beta users. You need an API key from the MOE Toolkit admin before installing.
      </p>
      <div class="card">
        <strong>Cloud endpoint:</strong> <code>{escape(base_url)}</code><br />
        <strong>Release archive:</strong> <a href="{escape(archive_url)}">{escape(archive_url)}</a>
      </div>
      <h2>Install</h2>
      <ol>
        <li>Request your personal beta API key from the admin.</li>
        <li>Run the install bootstrap command in Terminal on macOS.</li>
        <li>Restart Codex CLI, Claude Code, or OpenClaw after installation.</li>
      </ol>
      <h3>Codex CLI</h3>
      <pre><code>{codex_install_command}</code></pre>
      <h3>Claude Code</h3>
      <pre><code>{claude_install_command}</code></pre>
      <h3>OpenClaw</h3>
      <pre><code>{openclaw_install_command}</code></pre>
      <h3>CLI / Agent Direct Use</h3>
      <pre><code>moeskills config set --server-url {escape(base_url)} --api-key &lt;YOUR_KEY&gt;</code></pre>
      <pre><code>moeskills run --task "分析这个 CSV 并生成趋势图" --attach ./sales.csv --wait --json</code></pre>
      <h2>Verify</h2>
      <pre><code>moeskills doctor</code></pre>
      <pre><code>moeskills host doctor codex-cli</code></pre>
      <pre><code>moeskills host doctor claude-code</code></pre>
      <pre><code>moeskills host doctor openclaw --workspace-path &lt;OPENCLAW_WORKSPACE&gt;</code></pre>
      <h2>What gets installed</h2>
      <ul>
        <li><code>~/.local/bin/moeskills</code></li>
        <li><code>~/.local/bin/moe-connector</code> (compatibility alias)</li>
        <li><code>~/.moeskills/config.toml</code></li>
        <li><code>~/MOE Outputs</code></li>
        <li>Host registration for Codex CLI, Claude Code, or an OpenClaw agent workspace</li>
      </ul>
      <h2>Troubleshooting</h2>
      <ul>
        <li>If the install script cannot find <code>python3</code>, install Python 3.11+ first.</li>
        <li>If <code>doctor</code> reports authentication failure, confirm your API key was copied fully.</li>
        <li>If host registration succeeds but tools do not appear, restart the host client.</li>
        <li>OpenClaw installs prompt you to confirm the target agent workspace. If discovery fails, rerun with <code>--openclaw-workspace &lt;PATH&gt;</code>.</li>
      </ul>
    </main>
  </body>
</html>"""
        return HTMLResponse(html)

    @app.get("/install.sh", response_class=PlainTextResponse)
    async def install_script(
        current_settings: CloudSettings = Depends(get_settings),
    ) -> PlainTextResponse:
        base_url = current_settings.public_base_url.rstrip("/")
        script = "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'TMP_DIR="$(mktemp -d)"',
                'cleanup() { rm -rf "${TMP_DIR}"; }',
                "trap cleanup EXIT",
                f'ARCHIVE_URL="{base_url}/releases/moeskills-macos.tar.gz"',
                'ARCHIVE_PATH="${TMP_DIR}/moeskills-macos.tar.gz"',
                'curl -fsSL "${ARCHIVE_URL}" -o "${ARCHIVE_PATH}"',
                'LC_ALL=C tar -xzf "${ARCHIVE_PATH}" -C "${TMP_DIR}"',
                'bash "${TMP_DIR}/moeskills-release/install.sh" "$@"',
                "",
            ]
        )
        return PlainTextResponse(script)

    @app.api_route("/releases/moeskills-macos.tar.gz", methods=["GET", "HEAD"])
    @app.api_route("/releases/moe-connector-macos.tar.gz", methods=["GET", "HEAD"])
    async def download_release_archive() -> FileResponse:
        archive_path = get_release_archive_path()
        if not archive_path.exists():
            raise HTTPException(status_code=404, detail="Connector release archive not found.")
        return FileResponse(
            archive_path,
            filename=archive_path.name,
            media_type="application/gzip",
        )

    @app.post("/v1/files/upload", response_model=UploadRef)
    async def upload_file(
        file: UploadFile = File(...),
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> UploadRef:
        payload = await file.read()
        try:
            return cloud_service.save_upload(
                filename=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
                payload=payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/registry/tools/search", response_model=list[ToolSummary])
    async def search_registry_tools(
        capability: str | None = Query(default=None),
        input_type: str | None = Query(default=None),
        enabled: bool | None = Query(default=None),
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> list[ToolSummary]:
        return cloud_service.search_tools(
            capability=capability,
            input_type=input_type,
            enabled=enabled,
        )

    @app.get("/v1/registry/tools/{tool_id}", response_model=ToolSummary)
    async def get_registry_tool(
        tool_id: str,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> ToolSummary:
        try:
            return cloud_service.get_tool_summary(tool_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/registry/manifests/{tool_id}/{version}", response_model=ToolManifest)
    async def get_registry_manifest(
        tool_id: str,
        version: str,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> ToolManifest:
        try:
            return cloud_service.get_tool_manifest(tool_id, version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/telemetry/events", response_model=TelemetryEvent)
    @app.post("/v1/telemetry/connector-events", response_model=TelemetryEvent)
    async def record_connector_event(
        event: TelemetryEvent,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> TelemetryEvent:
        return cloud_service.record_connector_event(event)

    @app.post("/v1/tasks/execute", response_model=TaskAccepted)
    async def execute_task(
        request: RemoteTaskRequest,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> TaskAccepted:
        try:
            run = cloud_service.create_run(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return TaskAccepted(
            run_id=run.run_id,
            status=run.status,
            route_plan=run.route_plan,
        )

    @app.get("/v1/runs/{run_id}", response_model=RunRecord)
    async def get_run(
        run_id: str,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> RunRecord:
        try:
            return cloud_service.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}/artifacts", response_model=list[ArtifactRef])
    async def get_artifacts(
        run_id: str,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> list[ArtifactRef]:
        try:
            return cloud_service.list_artifacts(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/artifacts/{artifact_id}/download")
    async def download_artifact(
        artifact_id: str,
        cloud_service: CloudService = Depends(get_cloud_service),
        _: str = Depends(validate_api_key),
    ) -> FileResponse:
        try:
            target_path = cloud_service.get_artifact_path(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        filename = Path(target_path).name
        return FileResponse(target_path, filename=filename)

    return app
