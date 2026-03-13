from __future__ import annotations

from pathlib import Path

from moe_toolkit.connector import config as config_module
from moe_toolkit.connector.config import load_config, save_config
from moe_toolkit.schemas.common import ConnectorConfig


def test_save_and_load_config_roundtrip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    output_dir = tmp_path / "outputs"
    config = ConnectorConfig(
        server_url="http://127.0.0.1:8080",
        api_key="secret-key",
        host_client="codex-cli",
        output_dir=output_dir,
        request_timeout_seconds=45,
        max_upload_size_mb=50,
    )

    save_config(config, config_path=config_path)
    loaded = load_config(config_path=config_path)

    assert loaded == config
    assert output_dir.exists()


def test_config_file_is_owner_only_when_supported(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = ConnectorConfig(
        server_url="http://127.0.0.1:8080",
        api_key="secret-key",
        host_client="claude-code",
        output_dir=tmp_path / "outputs",
    )

    save_config(config, config_path=config_path)

    mode = config_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_load_config_migrates_legacy_default_config(tmp_path: Path, monkeypatch) -> None:
    default_path = tmp_path / ".moeskills" / "config.toml"
    legacy_path = tmp_path / ".moe-connector" / "config.toml"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        'server_url = "http://legacy.test"\n'
        'api_key = "legacy-key"\n'
        'host_client = "codex-cli"\n'
        f'output_dir = "{tmp_path / "outputs"}"\n'
        "request_timeout_seconds = 60\n"
        "max_upload_size_mb = 100\n"
        "run_poll_interval_seconds = 0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", default_path)
    monkeypatch.setattr(config_module, "LEGACY_DEFAULT_CONFIG_PATH", legacy_path)

    loaded = load_config(config_path=config_module.DEFAULT_CONFIG_PATH)

    assert default_path.exists()
    assert loaded.server_url == "http://legacy.test"
    assert loaded.api_key == "legacy-key"


def test_load_config_applies_moeskills_env_overrides(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config = ConnectorConfig(
        server_url="http://127.0.0.1:8080",
        api_key="secret-key",
        host_client="cli",
        output_dir=tmp_path / "outputs",
    )
    save_config(config, config_path=config_path)
    monkeypatch.setenv("MOESKILLS_SERVER_URL", "http://override.test")
    monkeypatch.setenv("MOESKILLS_API_KEY", "override-key")
    monkeypatch.setenv("MOESKILLS_OUTPUT_DIR", str(tmp_path / "override-outputs"))
    monkeypatch.setenv("MOESKILLS_REQUEST_TIMEOUT", "15")
    monkeypatch.setenv("MOESKILLS_RUN_POLL_INTERVAL", "0.5")

    loaded = load_config(config_path=config_path)

    assert loaded.server_url == "http://override.test"
    assert loaded.api_key == "override-key"
    assert loaded.output_dir == tmp_path / "override-outputs"
    assert loaded.request_timeout_seconds == 15
    assert loaded.run_poll_interval_seconds == 0.5
