from __future__ import annotations

import json
from pathlib import Path

from moe_toolkit.connector.hosts import (
    ClaudeCodeHostAdapter,
    CodexHostAdapter,
    SERVER_NAME,
)


def test_codex_adapter_install_and_uninstall(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
    adapter = CodexHostAdapter(config_path)

    install_result = adapter.install(
        connector_command="/Users/demo/.local/bin/moe-connector",
        connector_config_path=Path("/Users/demo/.moe-connector/config.toml"),
    )
    installed = config_path.read_text(encoding="utf-8")
    assert adapter.is_installed() is True
    uninstall_result = adapter.uninstall()
    removed = config_path.read_text(encoding="utf-8")

    assert install_result.changed is True
    assert f"[mcp_servers.{SERVER_NAME}]" in installed
    assert 'command = "/Users/demo/.local/bin/moe-connector"' in installed
    assert '"/Users/demo/.moe-connector/config.toml"' in installed
    assert adapter.is_installed() is False
    assert uninstall_result.changed is True
    assert f"[mcp_servers.{SERVER_NAME}]" not in removed


def test_claude_adapter_install_and_uninstall(tmp_path: Path) -> None:
    config_path = tmp_path / ".claude.json"
    config_path.write_text('{"model":"test","mcpServers":{}}\n', encoding="utf-8")
    adapter = ClaudeCodeHostAdapter(config_path)

    adapter.install(
        connector_command="/Users/demo/.local/bin/moe-connector",
        connector_config_path=Path("/Users/demo/.moe-connector/config.toml"),
    )
    installed = json.loads(config_path.read_text(encoding="utf-8"))
    assert adapter.is_installed() is True
    adapter.uninstall()
    removed = json.loads(config_path.read_text(encoding="utf-8"))

    assert SERVER_NAME in installed["mcpServers"]
    assert installed["mcpServers"][SERVER_NAME]["command"] == "/Users/demo/.local/bin/moe-connector"
    assert installed["mcpServers"][SERVER_NAME]["args"][-2:] == [
        "--config-path",
        "/Users/demo/.moe-connector/config.toml",
    ]
    assert SERVER_NAME not in removed["mcpServers"]
    assert adapter.is_installed() is False
