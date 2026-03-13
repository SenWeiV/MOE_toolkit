"""Configuration persistence for the MOE connector."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from moe_toolkit.schemas.common import ConnectorConfig

DEFAULT_CONFIG_DIR = Path.home() / ".moeskills"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
LEGACY_DEFAULT_CONFIG_DIR = Path.home() / ".moe-connector"
LEGACY_DEFAULT_CONFIG_PATH = LEGACY_DEFAULT_CONFIG_DIR / "config.toml"

ENV_SERVER_URL = "MOESKILLS_SERVER_URL"
ENV_API_KEY = "MOESKILLS_API_KEY"
ENV_OUTPUT_DIR = "MOESKILLS_OUTPUT_DIR"
ENV_REQUEST_TIMEOUT = "MOESKILLS_REQUEST_TIMEOUT"
ENV_RUN_POLL_INTERVAL = "MOESKILLS_RUN_POLL_INTERVAL"


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


def resolve_default_config_path(config_path: Path = DEFAULT_CONFIG_PATH) -> Path:
    """Migrates the legacy default config path on first access."""

    expanded_path = config_path.expanduser()
    if expanded_path != DEFAULT_CONFIG_PATH or expanded_path.exists():
        return expanded_path
    if LEGACY_DEFAULT_CONFIG_PATH.exists():
        expanded_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_DEFAULT_CONFIG_PATH, expanded_path)
    return expanded_path


def parse_config_toml(content: str) -> dict[str, str | int | float | Path]:
    """Parses the simple TOML subset used by the local connector config."""

    data: dict[str, str | int | float | Path] = {}
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
    return data


def load_persisted_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    allow_missing: bool = False,
) -> ConnectorConfig:
    """Loads persisted config without environment overrides."""

    resolved_path = resolve_default_config_path(config_path)
    if not resolved_path.exists():
        if allow_missing:
            return ConnectorConfig()
        raise FileNotFoundError(
            f"Connector config not found at {resolved_path}. Run `moeskills config set` first."
        )
    content = resolved_path.read_text(encoding="utf-8")
    return ConnectorConfig.model_validate(parse_config_toml(content))


def load_env_overrides() -> dict[str, str | int | float | Path]:
    """Returns CLI runtime config overrides sourced from environment variables."""

    overrides: dict[str, str | int | float | Path] = {}
    if os.environ.get(ENV_SERVER_URL):
        overrides["server_url"] = os.environ[ENV_SERVER_URL]
    if os.environ.get(ENV_API_KEY):
        overrides["api_key"] = os.environ[ENV_API_KEY]
    if os.environ.get(ENV_OUTPUT_DIR):
        overrides["output_dir"] = Path(os.environ[ENV_OUTPUT_DIR]).expanduser()
    if os.environ.get(ENV_REQUEST_TIMEOUT):
        overrides["request_timeout_seconds"] = int(os.environ[ENV_REQUEST_TIMEOUT])
    if os.environ.get(ENV_RUN_POLL_INTERVAL):
        overrides["run_poll_interval_seconds"] = float(os.environ[ENV_RUN_POLL_INTERVAL])
    return overrides


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


def load_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    allow_missing: bool = False,
    apply_env: bool = True,
) -> ConnectorConfig:
    """Loads connector configuration, optionally overlaying environment variables."""

    config = load_persisted_config(config_path=config_path, allow_missing=allow_missing)
    if not apply_env:
        return config
    overrides = load_env_overrides()
    if not overrides:
        return config
    return config.model_copy(update=overrides)
