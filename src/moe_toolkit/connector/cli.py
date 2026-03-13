"""CLI entrypoint for MOE Toolkit."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

from moe_toolkit.connector.client import CloudClient
from moe_toolkit.connector.config import DEFAULT_CONFIG_PATH, load_config, load_persisted_config, save_config
from moe_toolkit.connector.hosts import ClaudeCodeHostAdapter, CodexHostAdapter
from moe_toolkit.connector.openclaw import (
    OpenClawHostAdapter,
    OpenClawWorkspaceError,
    get_output_dir,
    resolve_attachment_path,
    resolve_workspace,
)
from moe_toolkit.schemas.common import ConnectorConfig, RoutePlan, RunRecord, TaskAccepted

HOST_CHOICES = ["claude-code", "codex-cli", "openclaw"]
STDIO_HOST_CHOICES = ["claude-code", "codex-cli"]
HOST_CLIENT_CHOICES = ["cli", *HOST_CHOICES]

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_UNSUPPORTED = 4
EXIT_RUN_FAILED = 5
EXIT_NETWORK = 6

LEGACY_COMMANDS = {"configure", "install", "uninstall", "serve", "openclaw"}


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def print_json(payload: Any) -> None:
    """Prints a single JSON document to stdout."""

    print(json.dumps(payload, ensure_ascii=True, default=_json_default))


def emit_error(
    message: str,
    *,
    exit_code: int,
    json_mode: bool = False,
    error_code: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Prints a structured or plain-text error and returns its exit code."""

    if json_mode:
        document = {
            "status": "error",
            "message": message,
            "exit_code": exit_code,
        }
        if error_code:
            document["error_code"] = error_code
        if payload:
            document.update(payload)
        print_json(document)
    else:
        if error_code:
            print(f"{message} [{error_code}]", file=sys.stderr)
        else:
            print(message, file=sys.stderr)
    return exit_code


def maybe_warn_legacy_invocation(command: str) -> None:
    """Emits a deprecation warning for legacy command shapes."""

    invoked_as = Path(sys.argv[0]).name
    if invoked_as == "moe-connector":
        print(
            "Warning: `moe-connector` is deprecated. Switch to `moeskills`.",
            file=sys.stderr,
        )
        return
    if command in LEGACY_COMMANDS:
        print(
            f"Warning: `{command}` is a legacy CLI form. Prefer the `moeskills` command groups.",
            file=sys.stderr,
        )


def build_parser(prog_name: str) -> argparse.ArgumentParser:
    """Builds the command-line parser."""

    parser = argparse.ArgumentParser(prog=prog_name)
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('moe-toolkit')}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config = subparsers.add_parser("config")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_set = config_subparsers.add_parser("set")
    config_set.add_argument("--server-url", default=None)
    config_set.add_argument("--api-key", default=None)
    config_set.add_argument("--output-dir", default=None)
    config_set.add_argument("--host-client", choices=HOST_CLIENT_CHOICES, default=None)
    config_set.add_argument("--request-timeout-seconds", type=int, default=None)
    config_set.add_argument("--run-poll-interval-seconds", type=float, default=None)
    config_set.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    config_set.add_argument("--json", action="store_true")

    config_show = config_subparsers.add_parser("show")
    config_show.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    config_show.add_argument("--json", action="store_true")

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    doctor.add_argument("--host", choices=HOST_CHOICES, action="append")
    doctor.add_argument("--workspace-path", default=None)
    doctor.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run")
    run.add_argument("--task", required=True)
    run.add_argument("--attach", action="append")
    run.add_argument("--session-id", default=None)
    run.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    run.add_argument("--output-dir", default=None)
    run.add_argument("--workspace-path", default=None)
    run.add_argument("--host-client", choices=HOST_CLIENT_CHOICES, default="cli")
    run.add_argument("--wait", action="store_true")
    run.add_argument("--json", action="store_true")

    runs = subparsers.add_parser("runs")
    runs_subparsers = runs.add_subparsers(dest="runs_command", required=True)
    runs_get = runs_subparsers.add_parser("get")
    runs_get.add_argument("run_id")
    runs_get.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    runs_get.add_argument("--json", action="store_true")

    artifacts = subparsers.add_parser("artifacts")
    artifacts_subparsers = artifacts.add_subparsers(dest="artifacts_command", required=True)
    artifacts_list = artifacts_subparsers.add_parser("list")
    artifacts_list.add_argument("run_id")
    artifacts_list.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    artifacts_list.add_argument("--json", action="store_true")

    artifacts_download = artifacts_subparsers.add_parser("download")
    artifacts_download.add_argument("run_id")
    artifacts_download.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    artifacts_download.add_argument("--output-dir", default=None)
    artifacts_download.add_argument("--json", action="store_true")

    registry = subparsers.add_parser("registry")
    registry_subparsers = registry.add_subparsers(dest="registry_command", required=True)
    registry_search = registry_subparsers.add_parser("search")
    registry_search.add_argument("--capability", default=None)
    registry_search.add_argument("--input-type", default=None)
    registry_search.add_argument("--enabled", choices=["true", "false"], default=None)
    registry_search.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    registry_search.add_argument("--json", action="store_true")

    registry_get = registry_subparsers.add_parser("get")
    registry_get.add_argument("tool_id")
    registry_get.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    registry_get.add_argument("--json", action="store_true")

    registry_manifest = registry_subparsers.add_parser("manifest")
    registry_manifest.add_argument("tool_id")
    registry_manifest.add_argument("--version", required=True)
    registry_manifest.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    registry_manifest.add_argument("--json", action="store_true")

    api = subparsers.add_parser("api")
    api.add_argument("method")
    api.add_argument("path")
    api.add_argument("--data", default=None)
    api.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    api.add_argument("--json", action="store_true")

    host = subparsers.add_parser("host")
    host_subparsers = host.add_subparsers(dest="host_command", required=True)
    host_install = host_subparsers.add_parser("install")
    host_install.add_argument("target", choices=HOST_CHOICES)
    host_install.add_argument("--command-path", default=None)
    host_install.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    host_install.add_argument("--workspace-path", default=None)
    host_install.add_argument("--json", action="store_true")

    host_uninstall = host_subparsers.add_parser("uninstall")
    host_uninstall.add_argument("target", choices=HOST_CHOICES)
    host_uninstall.add_argument("--workspace-path", default=None)
    host_uninstall.add_argument("--json", action="store_true")

    host_doctor = host_subparsers.add_parser("doctor")
    host_doctor.add_argument("targets", nargs="*", choices=HOST_CHOICES)
    host_doctor.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    host_doctor.add_argument("--workspace-path", default=None)
    host_doctor.add_argument("--json", action="store_true")

    host_serve = host_subparsers.add_parser("serve")
    host_serve.add_argument("--host", choices=STDIO_HOST_CHOICES, required=False)
    host_serve.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    legacy_configure = subparsers.add_parser("configure", help=argparse.SUPPRESS)
    legacy_configure.add_argument("--server-url", required=True)
    legacy_configure.add_argument("--api-key", required=True)
    legacy_configure.add_argument("--host-client", choices=HOST_CLIENT_CHOICES, default="cli")
    legacy_configure.add_argument("--output-dir")
    legacy_configure.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    legacy_install = subparsers.add_parser("install", help=argparse.SUPPRESS)
    legacy_install.add_argument("--host", choices=HOST_CHOICES, required=True)
    legacy_install.add_argument("--command-path", default=None)
    legacy_install.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    legacy_install.add_argument("--workspace-path", default=None)

    legacy_uninstall = subparsers.add_parser("uninstall", help=argparse.SUPPRESS)
    legacy_uninstall.add_argument("--host", choices=HOST_CHOICES, required=True)
    legacy_uninstall.add_argument("--workspace-path", default=None)

    legacy_serve = subparsers.add_parser("serve", help=argparse.SUPPRESS)
    legacy_serve.add_argument("--host", choices=STDIO_HOST_CHOICES, required=False)
    legacy_serve.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    legacy_openclaw = subparsers.add_parser("openclaw", help=argparse.SUPPRESS)
    legacy_openclaw_subparsers = legacy_openclaw.add_subparsers(dest="openclaw_command", required=True)
    legacy_openclaw_run = legacy_openclaw_subparsers.add_parser("run", help=argparse.SUPPRESS)
    legacy_openclaw_run.add_argument("--workspace-path", required=True)
    legacy_openclaw_run.add_argument("--task", required=True)
    legacy_openclaw_run.add_argument("--attach", action="append")
    legacy_openclaw_run.add_argument("--session-id", default=None)
    legacy_openclaw_run.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    return parser


def get_codex_config_path(home: Path | None = None) -> Path:
    base = home or Path.home()
    return base / ".codex" / "config.toml"


def get_claude_config_path(home: Path | None = None) -> Path:
    base = home or Path.home()
    return base / ".claude.json"


def resolve_openclaw_workspace_path(
    workspace_path: str | None,
    *,
    require_installed: bool = False,
) -> Path:
    """Resolves an OpenClaw workspace path from explicit path or interactive discovery."""

    return resolve_workspace(
        workspace_path=Path(workspace_path) if workspace_path else None,
        require_installed=require_installed,
    )


def _build_host_adapter(host: str, *, workspace_path: Path | None = None):
    if host == "codex-cli":
        return CodexHostAdapter(get_codex_config_path())
    if host == "claude-code":
        return ClaudeCodeHostAdapter(get_claude_config_path())
    if workspace_path is None:
        raise OpenClawWorkspaceError("OpenClaw workspace path is required.")
    return OpenClawHostAdapter(workspace_path)


def resolve_cli_command(command_path: str | None) -> str:
    """Resolves the CLI command written into host config files."""

    if command_path:
        return str(Path(command_path).expanduser().resolve())

    for candidate in ("moeskills", "moe-connector"):
        discovered = shutil.which(candidate)
        if discovered:
            return discovered

    argv_path = Path(sys.argv[0]).expanduser()
    if argv_path.exists():
        return str(argv_path.resolve())
    return "moeskills"


def _config_from_args(
    config_path: Path,
    *,
    allow_missing: bool = False,
    output_dir: str | None = None,
    host_client: str | None = None,
) -> ConnectorConfig:
    config = load_config(config_path, allow_missing=allow_missing)
    updates: dict[str, Any] = {}
    if output_dir is not None:
        updates["output_dir"] = Path(output_dir).expanduser()
    if host_client is not None:
        updates["host_client"] = host_client
    if updates:
        config = config.model_copy(update=updates)
    return config


def _validate_runtime_config(config: ConnectorConfig, *, json_mode: bool = False) -> int | None:
    if not config.api_key:
        return emit_error(
            "API key is missing. Run `moeskills config set --api-key ...` first.",
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="missing_api_key",
        )
    if not config.output_dir.exists():
        return emit_error(
            f"Output directory missing: {config.output_dir}",
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="missing_output_dir",
        )
    return None


def _route_plan_payload(route_plan: RoutePlan) -> dict[str, Any]:
    return route_plan.model_dump(mode="json")


def _run_payload(run: RunRecord, *, downloaded_paths: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": run.status,
        "run_id": run.run_id,
        "route_plan": _route_plan_payload(run.route_plan),
        "artifact_ids": run.artifact_ids,
    }
    if downloaded_paths is not None:
        payload["downloaded_paths"] = downloaded_paths
    if run.error_code:
        payload["error_code"] = run.error_code
    if run.detail:
        payload["detail"] = run.detail
    return payload


def _run_exit_code(run: RunRecord) -> int:
    if run.status == "success":
        return EXIT_OK
    if run.error_code == "unsupported_task" or run.route_plan.selection_reason == "no_match":
        return EXIT_UNSUPPORTED
    return EXIT_RUN_FAILED


def _load_attachment_paths(attachments: list[str], *, workspace_path: Path | None = None) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in attachments:
        if workspace_path is not None:
            resolved.append(resolve_attachment_path(workspace_path, raw_path))
            continue
        candidate = Path(raw_path).expanduser().resolve(strict=True)
        if not candidate.is_file():
            raise FileNotFoundError(f"Attachment must be a file: {candidate}")
        resolved.append(candidate)
    return resolved


def configure_connector(args: argparse.Namespace) -> int:
    """Writes connector configuration to disk."""

    current = load_persisted_config(Path(args.config_path), allow_missing=True)
    updates: dict[str, Any] = {}
    for field_name in (
        "server_url",
        "api_key",
        "host_client",
        "request_timeout_seconds",
        "run_poll_interval_seconds",
    ):
        value = getattr(args, field_name, None)
        if value is not None:
            updates[field_name] = value
    if args.output_dir is not None:
        updates["output_dir"] = Path(args.output_dir).expanduser()
    config = current.model_copy(update=updates)
    saved_path = save_config(config, config_path=Path(args.config_path))
    payload = {
        "status": "configured",
        "config_path": str(saved_path),
        "config": config.model_dump(mode="json"),
    }
    if getattr(args, "json", False):
        print_json(payload)
    else:
        print(f"Saved config to {saved_path}")
    return EXIT_OK


async def doctor_connector(
    config_path: Path,
    hosts: list[str] | None = None,
    workspace_path: str | None = None,
    *,
    json_mode: bool = False,
) -> int:
    """Runs a basic connector diagnosis."""

    try:
        config = load_config(config_path, allow_missing=True)
    except FileNotFoundError as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="missing_config",
        )

    config_error = _validate_runtime_config(config, json_mode=json_mode)
    if config_error is not None:
        return config_error

    client = CloudClient(config)
    try:
        health = await client.get_health()
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            f"Cloud health check failed: {exc}",
            exit_code=EXIT_NETWORK,
            json_mode=json_mode,
            error_code="health_check_failed",
        )

    host_payloads: list[dict[str, Any]] = []
    try:
        resolved_openclaw_workspace = None
        if hosts and "openclaw" in hosts:
            resolved_openclaw_workspace = resolve_openclaw_workspace_path(
                workspace_path,
                require_installed=False,
            )
        for host in hosts or []:
            adapter = _build_host_adapter(host, workspace_path=resolved_openclaw_workspace)
            host_payload: dict[str, Any] = {
                "host": host,
                "installed": adapter.is_installed(),
            }
            if host == "openclaw" and resolved_openclaw_workspace is not None:
                host_payload["workspace_path"] = str(resolved_openclaw_workspace)
            host_payloads.append(host_payload)
    except OpenClawWorkspaceError as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="openclaw_workspace_error",
        )

    payload = {
        "status": "ok",
        "server_url": config.server_url,
        "authenticated": health.authenticated is True,
        "output_dir": str(config.output_dir),
        "health": health.model_dump(mode="json"),
        "hosts": host_payloads,
    }
    if json_mode:
        print_json(payload)
    else:
        print(f"Cloud service reachable at {config.server_url}")
        print(f"Authenticated: {health.authenticated is True}")
        print(f"Output directory: {config.output_dir}")
        print(f"CLI command: {resolve_cli_command(None)}")
        for host_payload in host_payloads:
            print(f"Host registration [{host_payload['host']}]: {host_payload['installed']}")
            if "workspace_path" in host_payload:
                print(f"OpenClaw workspace: {host_payload['workspace_path']}")
    return EXIT_OK


def install_host(
    host: str,
    *,
    command_path: str | None,
    config_path: str,
    workspace_path: str | None = None,
    json_mode: bool = False,
) -> int:
    """Installs the CLI into the requested host config."""

    try:
        resolved_workspace = None
        if host == "openclaw":
            resolved_workspace = resolve_openclaw_workspace_path(
                workspace_path,
                require_installed=False,
            )
        adapter = _build_host_adapter(host, workspace_path=resolved_workspace)
        result = adapter.install(
            connector_command=resolve_cli_command(command_path),
            connector_config_path=Path(config_path),
        )
    except OpenClawWorkspaceError as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="openclaw_workspace_error",
        )

    payload = result.model_dump(mode="json")
    if json_mode:
        print_json(payload)
    else:
        print(f"{result.host}: {result.detail} -> {result.config_path}")
    return EXIT_OK


def uninstall_host(
    host: str,
    *,
    workspace_path: str | None = None,
    json_mode: bool = False,
) -> int:
    """Removes the CLI from the requested host config."""

    try:
        if host == "codex-cli":
            result = CodexHostAdapter(get_codex_config_path()).uninstall()
        elif host == "claude-code":
            result = ClaudeCodeHostAdapter(get_claude_config_path()).uninstall()
        else:
            resolved_workspace = resolve_openclaw_workspace_path(
                workspace_path,
                require_installed=True,
            )
            result = OpenClawHostAdapter(resolved_workspace).uninstall()
    except OpenClawWorkspaceError as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="openclaw_workspace_error",
        )

    payload = result.model_dump(mode="json")
    if json_mode:
        print_json(payload)
    else:
        print(f"{result.host}: {result.detail} -> {result.config_path}")
    return EXIT_OK


async def execute_run_command(
    *,
    task: str,
    attachments: list[str],
    session_id: str | None,
    config_path: Path,
    output_dir: str | None,
    workspace_path: str | None,
    wait_for_completion: bool,
    json_mode: bool,
    host_client: str,
) -> int:
    """Executes a high-level MOE task and optionally downloads its artifacts."""

    try:
        resolved_workspace = None
        if workspace_path is not None:
            resolved_workspace = resolve_openclaw_workspace_path(
                workspace_path,
                require_installed=False,
            )
        config = _config_from_args(
            config_path,
            allow_missing=True,
            output_dir=output_dir,
            host_client="openclaw" if resolved_workspace is not None else host_client,
        )
        if resolved_workspace is not None:
            config = config.model_copy(update={"output_dir": get_output_dir(resolved_workspace)})
            config.output_dir.mkdir(parents=True, exist_ok=True)
        config_error = _validate_runtime_config(config, json_mode=json_mode)
        if config_error is not None:
            return config_error

        attachment_paths = _load_attachment_paths(attachments, workspace_path=resolved_workspace)
        client = CloudClient(config)
        uploads = [await client.upload_file(path) for path in attachment_paths]
        accepted = await client.execute_task(
            task=task,
            attachments=[item.upload_id for item in uploads],
            session_id=session_id,
        )

        if not wait_for_completion and accepted.status not in {"failed"}:
            payload = {
                "status": accepted.status,
                "run_id": accepted.run_id,
                "route_plan": _route_plan_payload(accepted.route_plan),
            }
            if json_mode:
                print_json(payload)
            else:
                print(f"Run accepted: {accepted.run_id} ({accepted.status})")
            return EXIT_OK

        run = await client.get_run(accepted.run_id) if accepted.status == "failed" else await client.wait_for_run(accepted.run_id)
        downloaded_paths: list[str] = []
        if run.status == "success":
            artifacts = await client.get_artifacts(run.run_id)
            downloaded_paths = [
                str(await client.download_artifact(artifact, config.output_dir))
                for artifact in artifacts
            ]

        payload = _run_payload(run, downloaded_paths=downloaded_paths)
        if json_mode:
            print_json(payload)
        else:
            print(f"Run {run.run_id}: {run.status}")
            if downloaded_paths:
                for path in downloaded_paths:
                    print(path)
            elif run.detail:
                print(run.detail)
        return _run_exit_code(run)
    except FileNotFoundError as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="missing_attachment",
        )
    except (OpenClawWorkspaceError, ValueError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=json_mode,
            error_code="invalid_runtime_input",
        )
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=json_mode,
            error_code="cloud_request_failed",
        )


async def run_openclaw_task(args: argparse.Namespace) -> int:
    """Compatibility wrapper for older OpenClaw command shapes."""

    return await execute_run_command(
        task=args.task,
        attachments=args.attach or [],
        session_id=args.session_id,
        config_path=Path(args.config_path),
        output_dir=None,
        workspace_path=args.workspace_path,
        wait_for_completion=True,
        json_mode=True,
        host_client="openclaw",
    )


async def get_run_command(
    run_id: str,
    *,
    config_path: Path,
    json_mode: bool,
) -> int:
    """Loads a run record from the cloud API."""

    try:
        config = load_config(config_path, allow_missing=True)
        config_error = _validate_runtime_config(config, json_mode=json_mode)
        if config_error is not None:
            return config_error
        run = await CloudClient(config).get_run(run_id)
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=json_mode,
            error_code="cloud_request_failed",
        )

    payload = _run_payload(run)
    if json_mode:
        print_json(payload)
    else:
        print(f"Run {run.run_id}: {run.status}")
        if run.detail:
            print(run.detail)
    return _run_exit_code(run)


async def list_artifacts_command(
    run_id: str,
    *,
    config_path: Path,
    json_mode: bool,
) -> int:
    """Lists artifacts for a run."""

    try:
        config = load_config(config_path, allow_missing=True)
        config_error = _validate_runtime_config(config, json_mode=json_mode)
        if config_error is not None:
            return config_error
        artifacts = await CloudClient(config).get_artifacts(run_id)
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=json_mode,
            error_code="cloud_request_failed",
        )

    payload = {
        "run_id": run_id,
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }
    if json_mode:
        print_json(payload)
    else:
        print(f"Artifacts for {run_id}: {len(artifacts)}")
        for artifact in artifacts:
            print(artifact.filename)
    return EXIT_OK


async def download_artifacts_command(
    run_id: str,
    *,
    config_path: Path,
    output_dir: str | None,
    json_mode: bool,
) -> int:
    """Downloads all artifacts for a run."""

    try:
        config = _config_from_args(config_path, allow_missing=True, output_dir=output_dir)
        config_error = _validate_runtime_config(config, json_mode=json_mode)
        if config_error is not None:
            return config_error
        client = CloudClient(config)
        artifacts = await client.get_artifacts(run_id)
        downloaded_paths = [
            str(await client.download_artifact(artifact, config.output_dir))
            for artifact in artifacts
        ]
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=json_mode,
            error_code="cloud_request_failed",
        )

    payload = {
        "run_id": run_id,
        "downloaded_paths": downloaded_paths,
    }
    if json_mode:
        print_json(payload)
    else:
        print(f"Downloaded {len(downloaded_paths)} artifacts for {run_id}")
        for path in downloaded_paths:
            print(path)
    return EXIT_OK


async def registry_search_command(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config_path), allow_missing=True)
        config_error = _validate_runtime_config(config, json_mode=args.json)
        if config_error is not None:
            return config_error
        enabled = None if args.enabled is None else args.enabled == "true"
        tools = await CloudClient(config).search_tools(
            capability=args.capability,
            input_type=args.input_type,
            enabled=enabled,
        )
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=args.json,
            error_code="cloud_request_failed",
        )

    payload = [tool.model_dump(mode="json") for tool in tools]
    if args.json:
        print_json(payload)
    else:
        for tool in tools:
            print(f"{tool.tool_id}\t{tool.version}\t{tool.description}")
    return EXIT_OK


async def registry_get_command(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config_path), allow_missing=True)
        config_error = _validate_runtime_config(config, json_mode=args.json)
        if config_error is not None:
            return config_error
        tool = await CloudClient(config).get_tool(args.tool_id)
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=args.json,
            error_code="cloud_request_failed",
        )

    payload = tool.model_dump(mode="json")
    if args.json:
        print_json(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    return EXIT_OK


async def registry_manifest_command(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config_path), allow_missing=True)
        config_error = _validate_runtime_config(config, json_mode=args.json)
        if config_error is not None:
            return config_error
        manifest = await CloudClient(config).get_manifest(args.tool_id, args.version)
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=args.json,
            error_code="cloud_request_failed",
        )

    payload = manifest.model_dump(mode="json")
    if args.json:
        print_json(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    return EXIT_OK


def _parse_api_payload(raw_data: str | None) -> Any | None:
    if raw_data is None:
        return None
    if raw_data.startswith("@"):
        content = Path(raw_data[1:]).read_text(encoding="utf-8")
    else:
        content = raw_data
    return json.loads(content)


async def api_command(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config_path), allow_missing=True)
        config_error = _validate_runtime_config(config, json_mode=args.json)
        if config_error is not None:
            return config_error
        response = await CloudClient(config).request(
            args.method,
            args.path,
            json_body=_parse_api_payload(args.data),
        )
    except FileNotFoundError as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_CONFIG,
            json_mode=args.json,
            error_code="missing_request_payload",
        )
    except json.JSONDecodeError as exc:
        return emit_error(
            f"Invalid JSON payload: {exc}",
            exit_code=EXIT_USAGE,
            json_mode=args.json,
            error_code="invalid_json_payload",
        )
    except (httpx.HTTPError, OSError) as exc:
        return emit_error(
            str(exc),
            exit_code=EXIT_NETWORK,
            json_mode=args.json,
            error_code="cloud_request_failed",
        )

    body: Any
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        body = response.json()
    else:
        body = response.text

    payload = {
        "status_code": response.status_code,
        "ok": response.is_success,
        "body": body,
    }
    if args.json:
        print_json(payload)
    else:
        if isinstance(body, (dict, list)):
            print(json.dumps(body, indent=2, ensure_ascii=True))
        else:
            print(body)
    return EXIT_OK if response.is_success else EXIT_NETWORK


def serve_connector(args: argparse.Namespace) -> int:
    """Runs the local FastMCP connector server."""

    from moe_toolkit.connector.mcp_server import run_server

    run_server(Path(args.config_path))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""

    prog_name = Path(sys.argv[0]).name or "moeskills"
    parser = build_parser(prog_name)
    args = parser.parse_args(argv)
    maybe_warn_legacy_invocation(args.command)

    if args.command == "configure":
        args.json = False
        return configure_connector(args)
    if args.command == "config" and args.config_command == "set":
        return configure_connector(args)
    if args.command == "config" and args.config_command == "show":
        try:
            config = load_config(Path(args.config_path), allow_missing=True)
        except FileNotFoundError as exc:
            return emit_error(str(exc), exit_code=EXIT_CONFIG, json_mode=args.json, error_code="missing_config")
        payload = config.model_dump(mode="json")
        if args.json:
            print_json(payload)
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=True))
        return EXIT_OK

    if args.command == "doctor":
        return asyncio.run(
            doctor_connector(
                Path(args.config_path),
                hosts=args.host,
                workspace_path=args.workspace_path,
                json_mode=args.json,
            )
        )
    if args.command == "run":
        return asyncio.run(
            execute_run_command(
                task=args.task,
                attachments=args.attach or [],
                session_id=args.session_id,
                config_path=Path(args.config_path),
                output_dir=args.output_dir,
                workspace_path=args.workspace_path,
                wait_for_completion=args.wait,
                json_mode=args.json,
                host_client=args.host_client,
            )
        )
    if args.command == "runs" and args.runs_command == "get":
        return asyncio.run(get_run_command(args.run_id, config_path=Path(args.config_path), json_mode=args.json))
    if args.command == "artifacts" and args.artifacts_command == "list":
        return asyncio.run(
            list_artifacts_command(args.run_id, config_path=Path(args.config_path), json_mode=args.json)
        )
    if args.command == "artifacts" and args.artifacts_command == "download":
        return asyncio.run(
            download_artifacts_command(
                args.run_id,
                config_path=Path(args.config_path),
                output_dir=args.output_dir,
                json_mode=args.json,
            )
        )
    if args.command == "registry" and args.registry_command == "search":
        return asyncio.run(registry_search_command(args))
    if args.command == "registry" and args.registry_command == "get":
        return asyncio.run(registry_get_command(args))
    if args.command == "registry" and args.registry_command == "manifest":
        return asyncio.run(registry_manifest_command(args))
    if args.command == "api":
        return asyncio.run(api_command(args))

    if args.command == "host" and args.host_command == "install":
        return install_host(
            args.target,
            command_path=args.command_path,
            config_path=args.config_path,
            workspace_path=args.workspace_path,
            json_mode=args.json,
        )
    if args.command == "host" and args.host_command == "uninstall":
        return uninstall_host(args.target, workspace_path=args.workspace_path, json_mode=args.json)
    if args.command == "host" and args.host_command == "doctor":
        hosts = args.targets or HOST_CHOICES
        return asyncio.run(
            doctor_connector(
                Path(args.config_path),
                hosts=hosts,
                workspace_path=args.workspace_path,
                json_mode=args.json,
            )
        )
    if args.command == "host" and args.host_command == "serve":
        return serve_connector(args)

    if args.command == "install":
        return install_host(
            args.host,
            command_path=args.command_path,
            config_path=args.config_path,
            workspace_path=args.workspace_path,
        )
    if args.command == "uninstall":
        return uninstall_host(args.host, workspace_path=args.workspace_path)
    if args.command == "serve":
        return serve_connector(args)
    if args.command == "openclaw" and args.openclaw_command == "run":
        return asyncio.run(run_openclaw_task(args))

    parser.error(f"Unsupported command: {args.command}")
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
