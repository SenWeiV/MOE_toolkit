"""CLI entrypoint for the MOE connector."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

import httpx

from moe_toolkit.connector.client import CloudClient
from moe_toolkit.connector.config import DEFAULT_CONFIG_PATH, load_config, save_config
from moe_toolkit.connector.hosts import ClaudeCodeHostAdapter, CodexHostAdapter
from moe_toolkit.schemas.common import ConnectorConfig


def build_parser() -> argparse.ArgumentParser:
    """Builds the command-line parser."""

    parser = argparse.ArgumentParser(prog="moe-connector")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('moe-toolkit')}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure")
    configure.add_argument("--server-url", required=True)
    configure.add_argument("--api-key", required=True)
    configure.add_argument("--host-client", default="codex-cli")
    configure.add_argument("--output-dir")
    configure.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    doctor.add_argument("--host", choices=["claude-code", "codex-cli"], action="append")

    install = subparsers.add_parser("install")
    install.add_argument("--host", choices=["claude-code", "codex-cli"], required=True)
    install.add_argument("--command-path", default=None)
    install.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--host", choices=["claude-code", "codex-cli"], required=True)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", choices=["claude-code", "codex-cli"], required=False)
    serve.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))

    return parser


def get_codex_config_path(home: Path | None = None) -> Path:
    base = home or Path.home()
    return base / ".codex" / "config.toml"


def get_claude_config_path(home: Path | None = None) -> Path:
    base = home or Path.home()
    return base / ".claude.json"


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


def _build_host_adapter(host: str):
    if host == "codex-cli":
        return CodexHostAdapter(get_codex_config_path())
    return ClaudeCodeHostAdapter(get_claude_config_path())


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
    for host in inspected_hosts:
        adapter = _build_host_adapter(host)
        print(f"Host registration [{host}]: {adapter.is_installed()}")
    return 0


def install_host(args: argparse.Namespace) -> int:
    """Installs the connector into the requested host config."""

    adapter = _build_host_adapter(args.host)
    result = adapter.install(
        connector_command=resolve_connector_command(args.command_path),
        connector_config_path=Path(args.config_path),
    )
    print(f"{result.host}: {result.detail} -> {result.config_path}")
    return 0


def uninstall_host(args: argparse.Namespace) -> int:
    """Removes the connector from the requested host config."""

    if args.host == "codex-cli":
        result = CodexHostAdapter(get_codex_config_path()).uninstall()
    else:
        result = ClaudeCodeHostAdapter(get_claude_config_path()).uninstall()
    print(f"{result.host}: {result.detail} -> {result.config_path}")
    return 0


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
        return asyncio.run(doctor_connector(Path(args.config_path), hosts=args.host))
    if args.command == "install":
        return install_host(args)
    if args.command == "uninstall":
        return uninstall_host(args)
    if args.command == "serve":
        return serve_connector(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
