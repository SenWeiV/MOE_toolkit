"""Configuration persistence for the MOE connector."""

from __future__ import annotations

from pathlib import Path

from moe_toolkit.schemas.common import ConnectorConfig

DEFAULT_CONFIG_DIR = Path.home() / ".moe-connector"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"


def render_config_toml(config: ConnectorConfig) -> str:
    """Renders connector configuration as TOML."""

    return "\n".join(
        [
            f'server_url = "{config.server_url}"',
            f'api_key = "{config.api_key}"',
            f'host_client = "{config.host_client}"',
            f'output_dir = "{config.output_dir}"',
            f"request_timeout_seconds = {config.request_timeout_seconds}",
            f"max_upload_size_mb = {config.max_upload_size_mb}",
            f"run_poll_interval_seconds = {config.run_poll_interval_seconds}",
            "",
        ]
    )


def save_config(
    config: ConnectorConfig,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Path:
    """Persists connector config and ensures secure file permissions."""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_config_toml(config), encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except PermissionError:
        pass
    return config_path


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> ConnectorConfig:
    """Loads connector configuration from disk."""

    if not config_path.exists():
        raise FileNotFoundError(
            f"Connector config not found at {config_path}. Run `moe-connector configure` first."
        )

    content = config_path.read_text(encoding="utf-8")
    data: dict[str, str | int | float] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if raw_value.startswith('"') and raw_value.endswith('"'):
            data[key] = raw_value[1:-1]
        elif "." in raw_value:
            data[key] = float(raw_value)
        else:
            data[key] = int(raw_value)
    if "output_dir" in data and isinstance(data["output_dir"], str):
        data["output_dir"] = Path(data["output_dir"])
    return ConnectorConfig.model_validate(data)
