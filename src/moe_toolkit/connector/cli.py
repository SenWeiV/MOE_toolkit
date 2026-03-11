"""CLI entrypoint for the MOE connector."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

import httpx

from moe_toolkit.connector.client import CloudClient
from moe_toolkit.connector.config import DEFAULT_CONFIG_PATH, load_config, save_config
from moe_toolkit.connector.hosts import ClaudeCodeHostAdapter, CodexHostAdapter
from moe_toolkit.connector.openclaw import (
    OpenClawHostAdapter,
    OpenClawWorkspaceError,
    get_output_dir,
    resolve_attachment_path,
    resolve_workspace,
)
from moe_toolkit.schemas.common import ConnectorConfig

HOST_CHOICES = ["claude-code", "codex-cli", "openclaw"]
STDIO_HOST_CHOICES = ["claude-code", "codex-cli"]


def build_parser() -> argparse.ArgumentParser:
    """Builds the command-line parser."""

    parser = argparse.ArgumentParser(prog="moe-connector")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('moe-toolkit')}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure")
    configure.add_argument("--server-url", required=True)
    configure.add_argument("--api-key", required=True)
    configure.add_argument("--host-client", choices=HOST_CHOICES, default="codex-cli")
    configure.add_argument("--output-dir")
    configure.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    doctor.add_argument("--host", choices=HOST_CHOICES, action="append")
    doctor.add_argument("--workspace-path", default=None)

    install = subparsers.add_parser("install")
    install.add_argument("--host", choices=HOST_CHOICES, required=True)
    install.add_argument("--command-path", default=None)
    install.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    install.add_argument("--workspace-path", default=None)

    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--host", choices=HOST_CHOICES, required=True)
    uninstall.add_argument("--workspace-path", default=None)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", choices=STDIO_HOST_CHOICES, required=False)
    serve.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    openclaw = subparsers.add_parser("openclaw")
    openclaw_subparsers = openclaw.add_subparsers(dest="openclaw_command", required=True)
    openclaw_run = openclaw_subparsers.add_parser("run")
    openclaw_run.add_argument("--workspace-path", required=True)
    openclaw_run.add_argument("--task", required=True)
    openclaw_run.add_argument("--attach", action="append")
    openclaw_run.add_argument("--session-id", default=None)
    openclaw_run.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

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


def configure_connector(args: argparse.Namespace) -> int:
    """Writes connector configuration to disk."""

    output_dir = Path(args.output_dir) if args.output_dir else Path.home() / "MOE Outputs"
    config = ConnectorConfig(
        server_url=args.server_url,
        api_key=args.api_key,
        host_client=args.host_client,
        output_dir=output_dir,
    )
    saved_path = save_config(config, config_path=Path(args.config_path))
    print(f"Saved connector config to {saved_path}")
    return 0


def _build_host_adapter(host: str, *, workspace_path: Path | None = None):
    if host == "codex-cli":
        return CodexHostAdapter(get_codex_config_path())
    if host == "claude-code":
        return ClaudeCodeHostAdapter(get_claude_config_path())
    if workspace_path is None:
        raise OpenClawWorkspaceError("OpenClaw workspace path is required.")
    return OpenClawHostAdapter(workspace_path)


def resolve_connector_command(command_path: str | None) -> str:
    """Resolves the connector command written into host config files."""

    if command_path:
        return str(Path(command_path).expanduser().resolve())

    discovered = shutil.which("moe-connector")
    if discovered:
        return discovered

    argv_path = Path(sys.argv[0]).expanduser()
    if argv_path.exists():
        return str(argv_path.resolve())
    return "moe-connector"


async def doctor_connector(
    config_path: Path,
    hosts: list[str] | None = None,
    workspace_path: str | None = None,
) -> int:
    """Runs a basic connector diagnosis."""

    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not config.output_dir.exists():
        print(f"Output directory missing: {config.output_dir}", file=sys.stderr)
        return 1

    client = CloudClient(config)
    try:
        health = await client.get_health()
    except (httpx.HTTPError, OSError) as exc:
        print(f"Cloud health check failed: {exc}", file=sys.stderr)
        return 1

    if health.authenticated is False:
        print("Cloud is reachable but API key is invalid.", file=sys.stderr)
        return 1

    print(f"Cloud service reachable at {config.server_url}")
    print(f"Authenticated: {health.authenticated is True}")
    print(f"Output directory: {config.output_dir}")
    print(f"Connector command: {resolve_connector_command(None)}")
    inspected_hosts = hosts or ["codex-cli", "claude-code"]
    try:
        resolved_openclaw_workspace = None
        if "openclaw" in inspected_hosts:
            resolved_openclaw_workspace = resolve_openclaw_workspace_path(
                workspace_path,
                require_installed=False,
            )
        for host in inspected_hosts:
            adapter = _build_host_adapter(host, workspace_path=resolved_openclaw_workspace)
            print(f"Host registration [{host}]: {adapter.is_installed()}")
            if host == "openclaw" and resolved_openclaw_workspace is not None:
                print(f"OpenClaw workspace: {resolved_openclaw_workspace}")
    except OpenClawWorkspaceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def install_host(args: argparse.Namespace) -> int:
    """Installs the connector into the requested host config."""

    try:
        resolved_workspace = None
        if args.host == "openclaw":
            resolved_workspace = resolve_openclaw_workspace_path(
                args.workspace_path,
                require_installed=False,
            )
        adapter = _build_host_adapter(args.host, workspace_path=resolved_workspace)
        result = adapter.install(
            connector_command=resolve_connector_command(args.command_path),
            connector_config_path=Path(args.config_path),
        )
    except OpenClawWorkspaceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{result.host}: {result.detail} -> {result.config_path}")
    return 0


def uninstall_host(args: argparse.Namespace) -> int:
    """Removes the connector from the requested host config."""

    try:
        if args.host == "codex-cli":
            result = CodexHostAdapter(get_codex_config_path()).uninstall()
        elif args.host == "claude-code":
            result = ClaudeCodeHostAdapter(get_claude_config_path()).uninstall()
        else:
            workspace_path = resolve_openclaw_workspace_path(
                args.workspace_path,
                require_installed=True,
            )
            result = OpenClawHostAdapter(workspace_path).uninstall()
    except OpenClawWorkspaceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{result.host}: {result.detail} -> {result.config_path}")
    return 0


async def run_openclaw_task(args: argparse.Namespace) -> int:
    """Executes a high-level MOE task for OpenClaw and downloads artifacts to the workspace."""

    try:
        workspace_path = resolve_openclaw_workspace_path(
            args.workspace_path,
            require_installed=False,
        )
        config = load_config(Path(args.config_path))
        output_dir = get_output_dir(workspace_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        effective_config = config.model_copy(
            update={
                "host_client": "openclaw",
                "output_dir": output_dir,
            }
        )
        client = CloudClient(effective_config)
        attachment_paths = [
            resolve_attachment_path(workspace_path, raw_path)
            for raw_path in (args.attach or [])
        ]
        uploads = [await client.upload_file(path) for path in attachment_paths]
        accepted = await client.execute_task(
            task=args.task,
            attachments=[item.upload_id for item in uploads],
            session_id=args.session_id,
        )
        run = await client.wait_for_run(accepted.run_id)
        artifacts = await client.get_artifacts(accepted.run_id)
        downloaded_paths = [
            str(await client.download_artifact(artifact, output_dir))
            for artifact in artifacts
        ]
        payload = {
            "status": run.status,
            "run_id": run.run_id,
            "route_plan": run.route_plan.model_dump(mode="json"),
            "downloaded_paths": downloaded_paths,
        }
        if run.error_code:
            payload["error_code"] = run.error_code
        if run.detail:
            payload["detail"] = run.detail
        print(json.dumps(payload, ensure_ascii=True))
        return 0 if run.status == "success" else 1
    except (FileNotFoundError, OpenClawWorkspaceError, httpx.HTTPError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def serve_connector(args: argparse.Namespace) -> int:
    """Runs the local FastMCP connector server."""

    from moe_toolkit.connector.mcp_server import run_server

    run_server(Path(args.config_path))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "configure":
        return configure_connector(args)
    if args.command == "doctor":
        return asyncio.run(
            doctor_connector(
                Path(args.config_path),
                hosts=args.host,
                workspace_path=args.workspace_path,
            )
        )
    if args.command == "install":
        return install_host(args)
    if args.command == "uninstall":
        return uninstall_host(args)
    if args.command == "serve":
        return serve_connector(args)
    if args.command == "openclaw" and args.openclaw_command == "run":
        return asyncio.run(run_openclaw_task(args))
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
