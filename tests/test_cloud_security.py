from __future__ import annotations

import pytest
from fastapi import HTTPException

from moe_toolkit.cloud.security import extract_bearer_token, is_authorized, require_authorization
from moe_toolkit.cloud.settings import CloudSettings


def test_extract_bearer_token_handles_missing_and_malformed_headers() -> None:
    assert extract_bearer_token(None) is None
    assert extract_bearer_token("Basic abc") is None
    assert extract_bearer_token("Bearer secret-token") == "secret-token"


def test_is_authorized_and_require_authorization_validate_tokens() -> None:
    settings = CloudSettings(api_keys_raw="alpha-key,beta-key")

    assert is_authorized(settings, "Bearer alpha-key") is True
    assert is_authorized(settings, "Bearer wrong-key") is False
    assert require_authorization(settings, "Bearer beta-key") == "beta-key"

    with pytest.raises(HTTPException) as exc_info:
        require_authorization(settings, "Bearer wrong-key")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or missing API key."


def test_authorization_accepts_persisted_beta_keys(tmp_path) -> None:
    store_path = tmp_path / "admin" / "api_keys.json"
    beta_key = "sk_beta_demo"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        (
            '{\n'
            '  "keys": [\n'
            '    {\n'
            '      "key_id": "demo",\n'
            '      "owner_name": "Alice",\n'
            '      "contact": "alice@example.com",\n'
            f'      "api_key": "{beta_key}",\n'
            '      "status": "active",\n'
            '      "created_at": "2026-03-09T00:00:00+00:00",\n'
            '      "revoked_at": null,\n'
            '      "note": "",\n'
            '      "host_client": "codex-cli"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    settings = CloudSettings(storage_root=tmp_path)

    assert is_authorized(settings, f"Bearer {beta_key}") is True
    assert require_authorization(settings, f"Bearer {beta_key}") == beta_key
