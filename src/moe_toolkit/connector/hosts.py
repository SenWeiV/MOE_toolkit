"""Host integration helpers for Claude Code and Codex CLI."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from moe_toolkit.schemas.common import HostInstallResult

SERVER_NAME = "moe_toolkit"


@dataclass(slots=True)
class HostCommandSpec:
    """Represents the connector command registered with a host."""

    command: str
    args: list[str]


def build_command_spec(
    host: str,
    *,
    connector_command: str = "moe-connector",
    connector_config_path: Path | None = None,
) -> HostCommandSpec:
    """Builds the connector command spec for a given host."""

    args = ["serve", "--host", host]
    if connector_config_path is not None:
        args.extend(["--config-path", str(connector_config_path)])
    return HostCommandSpec(command=connector_command, args=args)


class CodexHostAdapter:
    """Installs and removes the connector from Codex CLI config."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def install(
        self,
        *,
        connector_command: str = "moe-connector",
        connector_config_path: Path | None = None,
    ) -> HostInstallResult:
        spec = build_command_spec(
            "codex-cli",
            connector_command=connector_command,
            connector_config_path=connector_config_path,
        )
        content = self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
        updated = upsert_codex_server_block(content, SERVER_NAME, spec)
        changed = updated != content
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(updated, encoding="utf-8")
        return HostInstallResult(
            host="codex-cli",
            config_path=self.config_path,
            changed=changed,
            detail="Codex MCP server entry installed",
        )

    def is_installed(self) -> bool:
        content = self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
        pattern = re.compile(rf"(?m)^\[mcp_servers\.{re.escape(SERVER_NAME)}\]$")
        return pattern.search(content) is not None

    def uninstall(self) -> HostInstallResult:
        content = self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
        updated = remove_codex_server_block(content, SERVER_NAME)
        changed = updated != content
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(updated, encoding="utf-8")
        return HostInstallResult(
            host="codex-cli",
            config_path=self.config_path,
            changed=changed,
            detail="Codex MCP server entry removed",
        )


class ClaudeCodeHostAdapter:
    """Installs and removes the connector from Claude Code config."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def install(
        self,
        *,
        connector_command: str = "moe-connector",
        connector_config_path: Path | None = None,
    ) -> HostInstallResult:
        spec = build_command_spec(
            "claude-code",
            connector_command=connector_command,
            connector_config_path=connector_config_path,
        )
        data = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        data.setdefault("mcpServers", {})
        existing_entry = data["mcpServers"].get(SERVER_NAME)
        next_entry = {
            "type": "stdio",
            "command": spec.command,
            "args": spec.args,
            "env": {},
        }
        data["mcpServers"][SERVER_NAME] = next_entry
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return HostInstallResult(
            host="claude-code",
            config_path=self.config_path,
            changed=existing_entry != next_entry,
            detail="Claude Code MCP server entry installed",
        )

    def is_installed(self) -> bool:
        data = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        mcp_servers = data.get("mcpServers", {})
        return SERVER_NAME in mcp_servers

    def uninstall(self) -> HostInstallResult:
        data = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        changed = False
        mcp_servers = data.get("mcpServers", {})
        if SERVER_NAME in mcp_servers:
            del mcp_servers[SERVER_NAME]
            changed = True
        if "mcpServers" not in data:
            data["mcpServers"] = {}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return HostInstallResult(
            host="claude-code",
            config_path=self.config_path,
            changed=changed,
            detail="Claude Code MCP server entry removed",
        )


def upsert_codex_server_block(
    content: str,
    server_name: str,
    spec: HostCommandSpec,
) -> str:
    """Upserts a single Codex MCP server block."""

    block = "\n".join(
        [
            f"[mcp_servers.{server_name}]",
            f"command = {json.dumps(spec.command, ensure_ascii=True)}",
            "args = [" + ", ".join(json.dumps(arg, ensure_ascii=True) for arg in spec.args) + "]",
        ]
    )
    cleaned = remove_codex_server_block(content, server_name).strip()
    if cleaned:
        return cleaned + "\n\n" + block + "\n"
    return block + "\n"


def remove_codex_server_block(content: str, server_name: str) -> str:
    """Removes a single Codex MCP server block from TOML-like config."""

    pattern = re.compile(
        rf"(?ms)^\[mcp_servers\.{re.escape(server_name)}\]\n.*?(?=^\[|\Z)"
    )
    updated = re.sub(pattern, "", content).strip()
    return updated + ("\n" if updated else "")
