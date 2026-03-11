from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from moe_toolkit.admin import beta_keys
from moe_toolkit.cloud.app import create_app
from moe_toolkit.cloud.settings import CloudSettings


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_admin_routes_return_404_when_disabled(tmp_path: Path) -> None:
    app = create_app(CloudSettings(storage_root=tmp_path, api_keys_raw="alpha-key"))
    with TestClient(app) as client:
        response = client.get("/admin/login")

    assert response.status_code == 404


def test_admin_dashboard_issue_revoke_and_download_email(tmp_path: Path) -> None:
    settings = CloudSettings(
        storage_root=tmp_path,
        api_keys_raw="env-key",
        admin_username="ops",
        admin_password="secret-password",
        admin_session_secret="session-secret",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        login_page = client.get("/admin/login")
        assert login_page.status_code == 200
        assert "MOE Admin" in login_page.text

        login_response = client.post(
            "/admin/login",
            data={"username": "ops", "password": "secret-password"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303
        assert login_response.headers["location"].startswith("/admin?")

        dashboard_response = client.get("/admin")
        assert dashboard_response.status_code == 200
        assert '<option value="openclaw">openclaw</option>' in dashboard_response.text
        csrf_token = extract_csrf_token(dashboard_response.text)

        issue_response = client.post(
            "/admin/issue",
            data={
                "csrf_token": csrf_token,
                "owner_name": "Alice",
                "contact": "alice@example.com",
                "note": "design partner",
                "host_client": "openclaw",
            },
            follow_redirects=False,
        )
        assert issue_response.status_code == 303

        records = beta_keys.list_keys(store_path=settings.resolved_api_key_store_path, status="all")
        assert len(records) == 1
        record = records[0]

        protected_response = client.post(
            "/v1/files/upload",
            files={"file": ("sales.csv", b"month,value\n1,10\n", "text/csv")},
            headers={"Authorization": f"Bearer {record.api_key}"},
        )
        assert protected_response.status_code == 200

        email_response = client.get(f"/admin/email-template/{record.key_id}.txt")
        assert email_response.status_code == 200
        assert record.api_key in email_response.text
        assert "curl -fsSL" in email_response.text
        assert "--host openclaw" in email_response.text

        manifest_response = client.get("/admin/email-manifest.csv?status=active")
        assert manifest_response.status_code == 200
        assert record.key_id in manifest_response.text

        revoke_response = client.post(
            "/admin/revoke",
            data={"csrf_token": csrf_token, "key_id": record.key_id},
            follow_redirects=False,
        )
        assert revoke_response.status_code == 303

        revoked_upload = client.post(
            "/v1/files/upload",
            files={"file": ("sales.csv", b"month,value\n1,10\n", "text/csv")},
            headers={"Authorization": f"Bearer {record.api_key}"},
        )
        assert revoked_upload.status_code == 401


def test_admin_login_rate_limit_triggers_after_failures(tmp_path: Path) -> None:
    app = create_app(
        CloudSettings(
            storage_root=tmp_path,
            admin_username="ops",
            admin_password="secret-password",
            admin_session_secret="session-secret",
            admin_login_max_attempts=1,
            admin_login_window_seconds=60,
        )
    )

    with TestClient(app) as client:
        first = client.post(
            "/admin/login",
            data={"username": "ops", "password": "wrong"},
        )
        second = client.post(
            "/admin/login",
            data={"username": "ops", "password": "wrong"},
        )

    assert first.status_code == 401
    assert "Invalid username or password." in first.text
    assert second.status_code == 429
    assert "Too many failed login attempts" in second.text
