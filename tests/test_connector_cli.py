from __future__ import annotations

from pathlib import Path

import pytest

from moe_toolkit.connector import cli as cli_module
from moe_toolkit.schemas.common import HealthComponent, HealthResponse


def test_cli_configure_writes_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"

    exit_code = cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "codex-cli",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
        ]
    )

    assert exit_code == 0
    content = config_path.read_text(encoding="utf-8")
    assert 'server_url = "http://127.0.0.1:8080"' in content
    assert 'api_key = "secret-key"' in content


@pytest.mark.asyncio
async def test_cli_doctor_returns_success_with_healthy_cloud(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "connector.toml"
    output_dir = tmp_path / "outputs"
    cli_module.main(
        [
            "configure",
            "--server-url",
            "http://127.0.0.1:8080",
            "--api-key",
            "secret-key",
            "--host-client",
            "codex-cli",
            "--output-dir",
            str(output_dir),
            "--config-path",
            str(config_path),
        ]
    )

    async def fake_get_health(self) -> HealthResponse:  # noqa: ARG001
        return HealthResponse(
            service="moe-cloud",
            version="0.1.0",
            healthy=True,
            authenticated=True,
            components=[HealthComponent(name="api", healthy=True, detail="ok")],
        )

    monkeypatch.setattr(cli_module.CloudClient, "get_health", fake_get_health)

    exit_code = await cli_module.doctor_connector(config_path)

    assert exit_code == 0


def test_cli_install_and_uninstall_codex(tmp_path: Path, monkeypatch) -> None:
    codex_config = tmp_path / "config.toml"
    codex_config.write_text('model = "gpt-5.4"\n', encoding="utf-8")
    monkeypatch.setattr(cli_module, "get_codex_config_path", lambda home=None: codex_config)

    install_code = cli_module.main(
        [
            "install",
            "--host",
            "codex-cli",
            "--command-path",
            str(tmp_path / "bin" / "moe-connector"),
            "--config-path",
            str(tmp_path / ".moe-connector" / "config.toml"),
        ]
    )
    installed = codex_config.read_text(encoding="utf-8")
    uninstall_code = cli_module.main(["uninstall", "--host", "codex-cli"])
    removed = codex_config.read_text(encoding="utf-8")

    assert install_code == 0
    assert uninstall_code == 0
    assert "[mcp_servers.moe_toolkit]" in installed
    assert f'command = "{tmp_path / "bin" / "moe-connector"}"' in installed
    assert f'"{tmp_path / ".moe-connector" / "config.toml"}"' in installed
    assert "[mcp_servers.moe_toolkit]" not in removed
