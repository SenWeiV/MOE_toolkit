from __future__ import annotations

from pathlib import Path

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

