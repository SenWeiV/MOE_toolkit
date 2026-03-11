"""Settings for the MOE cloud API."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from moe_toolkit.admin.beta_keys import load_records


class CloudSettings(BaseSettings):
    """Environment-backed settings for the cloud API."""

    model_config = SettingsConfigDict(
        env_prefix="MOE_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    public_base_url: str = "${MOE_PUBLIC_BASE_URL}"
    api_keys_raw: str = ""
    api_key_store_path: Path | None = None
    storage_root: Path = Field(default_factory=lambda: Path.cwd() / ".state")
    execution_backend: str = "inline"
    docker_binary: str = "docker"
    docker_host_storage_root: Path | None = None
    docker_network_mode: str = "none"
    embedded_worker_enabled: bool = True
    queue_poll_interval_seconds: float = 0.1
    queue_claim_timeout_seconds: int = 300
    cleanup_interval_seconds: int = 60
    service_name: str = "moe-cloud"
    service_version: str = "0.1.0"
    admin_username: str = ""
    admin_password: str = ""
    admin_session_secret: str = ""
    admin_session_max_age_seconds: int = 28800
    admin_login_window_seconds: int = 300
    admin_login_max_attempts: int = 5

    @property
    def resolved_api_key_store_path(self) -> Path:
        """Returns the persistent API key store path."""

        return self.api_key_store_path or (self.storage_root / "admin" / "api_keys.json")

    @property
    def persisted_api_keys(self) -> set[str]:
        """Returns active API keys from the persistent store."""

        store_path = self.resolved_api_key_store_path
        try:
            records = load_records(store_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return set()
        return {
            record.api_key
            for record in records
            if record.status == "active"
        }

    @property
    def api_keys(self) -> set[str]:
        """Returns the full set of accepted API keys."""

        return {
            token.strip()
            for token in self.api_keys_raw.split(",")
            if token.strip()
        } | self.persisted_api_keys

    @property
    def admin_enabled(self) -> bool:
        """Returns whether the minimal admin UI is enabled."""

        return bool(
            self.admin_username.strip()
            and self.admin_password
            and self.admin_session_secret
        )
