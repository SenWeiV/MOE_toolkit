from __future__ import annotations

import csv
from pathlib import Path

from moe_toolkit.admin import beta_keys


def test_issue_and_list_active_keys(tmp_path: Path) -> None:
    store_path = tmp_path / "api_keys.json"

    record = beta_keys.issue_key(
        store_path=store_path,
        owner_name="Alice",
        contact="alice@example.com",
        note="first beta user",
    )

    listed = beta_keys.list_keys(store_path=store_path, status="active")

    assert len(listed) == 1
    assert listed[0].key_id == record.key_id
    assert listed[0].api_key.startswith("sk_beta_")
    assert listed[0].contact == "alice@example.com"
    assert listed[0].host_client == "codex-cli"
    assert store_path.exists()


def test_revoke_key_excludes_it_from_active_env(tmp_path: Path) -> None:
    store_path = tmp_path / "api_keys.json"
    first = beta_keys.issue_key(store_path=store_path, owner_name="Alice")
    second = beta_keys.issue_key(store_path=store_path, owner_name="Bob")

    revoked = beta_keys.revoke_key(store_path=store_path, key_id=first.key_id)
    env_value = beta_keys.render_env_value(store_path)

    assert revoked.status == "revoked"
    assert first.api_key not in env_value
    assert second.api_key in env_value


def test_render_install_command_uses_public_install_endpoint() -> None:
    command = beta_keys.render_install_command(
        api_key="sk_beta_demo",
        server_url="${MOE_PUBLIC_BASE_URL}",
        host="codex-cli",
    )

    assert "curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh" in command
    assert "--api-key sk_beta_demo" in command
    assert "--host codex-cli" in command


def test_render_email_body_includes_beta_links() -> None:
    record = beta_keys.BetaKeyRecord(
        key_id="demo",
        owner_name="Alice",
        contact="alice@example.com",
        api_key="sk_beta_demo",
        status="active",
        created_at="2026-03-09T00:00:00+00:00",
        host_client="claude-code",
    )

    body = beta_keys.render_email_body(record, server_url="${MOE_PUBLIC_BASE_URL}")

    assert "MOE Toolkit Beta 已为你开通" in body
    assert "${MOE_PUBLIC_BASE_URL}/beta" in body
    assert "--host claude-code" in body


def test_bulk_issue_from_csv_exports_templates(tmp_path: Path) -> None:
    store_path = tmp_path / "api_keys.json"
    input_csv = tmp_path / "users.csv"
    output_dir = tmp_path / "exports"
    input_csv.write_text(
        "owner_name,contact,note,host\n"
        "Alice,alice@example.com,design partner,codex-cli\n"
        "Bob,bob@example.com,,claude-code\n",
        encoding="utf-8",
    )

    records, issued_csv_path, manifest_path = beta_keys.bulk_issue_from_csv(
        store_path=store_path,
        csv_path=input_csv,
        output_dir=output_dir,
        server_url="${MOE_PUBLIC_BASE_URL}",
    )

    assert len(records) == 2
    assert issued_csv_path.exists()
    assert manifest_path.exists()
    assert records[1].host_client == "claude-code"
    email_files = sorted((output_dir / "emails").glob("*.txt"))
    assert len(email_files) == 2
    assert "sk_beta_" in email_files[0].read_text(encoding="utf-8")

    with issued_csv_path.open("r", encoding="utf-8", newline="") as handle:
        issued_rows = list(csv.DictReader(handle))
    assert issued_rows[0]["owner_name"] == "Alice"
    assert "--host codex-cli" in issued_rows[0]["install_command"]

    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        manifest_rows = list(csv.DictReader(handle))
    assert manifest_rows[1]["contact"] == "bob@example.com"
    assert manifest_rows[1]["host_client"] == "claude-code"


def test_export_emails_filters_existing_records(tmp_path: Path) -> None:
    store_path = tmp_path / "api_keys.json"
    first = beta_keys.issue_key(store_path=store_path, owner_name="Alice", host_client="codex-cli")
    second = beta_keys.issue_key(store_path=store_path, owner_name="Bob", host_client="claude-code")
    beta_keys.revoke_key(store_path=store_path, key_id=first.key_id)
    output_dir = tmp_path / "exports"

    exit_code = beta_keys.main(
        [
            "--store-path",
            str(store_path),
            "export-emails",
            "--output-dir",
            str(output_dir),
            "--status",
            "active",
        ]
    )

    assert exit_code == 0
    email_files = sorted((output_dir / "emails").glob("*.txt"))
    assert len(email_files) == 1
    assert second.key_id in email_files[0].name
    assert first.key_id not in email_files[0].name


def test_cli_issue_and_render_env(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "api_keys.json"

    exit_code = beta_keys.main(
        [
            "--store-path",
            str(store_path),
            "issue",
            "--owner-name",
            "Alice",
            "--contact",
            "alice@example.com",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "install_command:" in output
    assert "api_key=sk_beta_" in output
    assert "host_client=codex-cli" in output

    render_exit_code = beta_keys.main(
        [
            "--store-path",
            str(store_path),
            "render-env",
            "--prefix",
        ]
    )
    render_output = capsys.readouterr().out

    assert render_exit_code == 0
    assert render_output.startswith("MOE_API_KEYS_RAW=sk_beta_")


def test_cli_bulk_issue_prints_export_paths(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "api_keys.json"
    input_csv = tmp_path / "users.csv"
    output_dir = tmp_path / "exports"
    input_csv.write_text("owner_name,contact\nAlice,alice@example.com\n", encoding="utf-8")

    exit_code = beta_keys.main(
        [
            "--store-path",
            str(store_path),
            "bulk-issue",
            "--input-csv",
            str(input_csv),
            "--output-dir",
            str(output_dir),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "issued_count=1" in output
    assert "email_manifest=" in output
