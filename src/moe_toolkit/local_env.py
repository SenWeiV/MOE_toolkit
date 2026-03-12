"""Helpers for local-only environment defaults."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

SAFE_DEFAULT_PUBLIC_BASE_URL = "http://127.0.0.1:8080"
SAFE_DEFAULT_REMOTE_HOST = "deploy@127.0.0.1"


def _candidate_roots() -> list[Path]:
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    module_path = Path(__file__).resolve()
    candidates.extend(module_path.parents)
    return candidates


def project_root() -> Path:
    """Returns the project root when running from a repo checkout."""

    for candidate in _candidate_roots():
        if (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd().resolve()


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


@lru_cache(maxsize=1)
def load_local_env_defaults() -> dict[str, str]:
    """Loads `.env.local` defaults without overriding real environment vars."""

    env_file = project_root() / ".env.local"
    if not env_file.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key.strip()] = _strip_wrapping_quotes(value.strip())
    return loaded


def env_or_local(key: str, default: str) -> str:
    """Returns shell env first, then `.env.local`, then the safe default."""

    if key in os.environ:
        return os.environ[key]
    return load_local_env_defaults().get(key, default)


def default_public_base_url() -> str:
    return env_or_local("MOE_PUBLIC_BASE_URL", SAFE_DEFAULT_PUBLIC_BASE_URL)


def default_remote_host() -> str:
    return env_or_local("MOE_REMOTE_HOST", SAFE_DEFAULT_REMOTE_HOST)
