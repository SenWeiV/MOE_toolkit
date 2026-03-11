"""Admin CLI for issuing and revoking MOE Toolkit beta API keys."""

from __future__ import annotations

import argparse
import csv
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

DEFAULT_STORE_PATH = Path.home() / ".moe-toolkit-beta" / "api_keys.json"
DEFAULT_SERVER_URL = "${MOE_PUBLIC_BASE_URL}"
SUPPORTED_HOSTS = ("claude-code", "codex-cli")


@dataclass(slots=True)
class BetaKeyRecord:
    """Persisted metadata for a single beta API key."""

    key_id: str
    owner_name: str
    contact: str
    api_key: str
    status: Literal["active", "revoked"]
    created_at: str
    revoked_at: str | None = None
    note: str = ""
    host_client: Literal["claude-code", "codex-cli"] = "codex-cli"


def utc_now() -> str:
    """Returns a JSON-friendly UTC timestamp."""

    return datetime.now(UTC).isoformat()


def load_records(store_path: Path) -> list[BetaKeyRecord]:
    """Loads beta key records from disk."""

    if not store_path.exists():
        return []
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    raw_records = payload.get("keys", [])
    return [BetaKeyRecord(**item) for item in raw_records]


def save_records(store_path: Path, records: list[BetaKeyRecord]) -> Path:
    """Persists beta key records to disk."""

    store_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"keys": [asdict(record) for record in records]}
    store_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        store_path.chmod(0o600)
    except PermissionError:
        pass
    return store_path


def generate_api_key() -> str:
    """Generates a beta-scoped API key."""

    return f"sk_beta_{secrets.token_hex(24)}"


def normalize_host(host: str | None, *, default_host: str = "codex-cli") -> Literal["claude-code", "codex-cli"]:
    """Validates and normalizes a host client value."""

    candidate = (host or default_host).strip() or default_host
    if candidate not in SUPPORTED_HOSTS:
        allowed = ", ".join(SUPPORTED_HOSTS)
        raise ValueError(f"Unsupported host '{candidate}'. Expected one of: {allowed}")
    return candidate  # type: ignore[return-value]


def issue_key(
    *,
    store_path: Path,
    owner_name: str,
    contact: str = "",
    note: str = "",
    host_client: str = "codex-cli",
) -> BetaKeyRecord:
    """Creates and stores a new beta API key."""

    normalized_owner_name = owner_name.strip()
    if not normalized_owner_name:
        raise ValueError("owner_name must not be empty.")
    records = load_records(store_path)
    record = BetaKeyRecord(
        key_id=secrets.token_hex(8),
        owner_name=normalized_owner_name,
        contact=contact,
        api_key=generate_api_key(),
        status="active",
        created_at=utc_now(),
        note=note,
        host_client=normalize_host(host_client),
    )
    records.append(record)
    save_records(store_path, records)
    return record


def revoke_key(*, store_path: Path, key_id: str) -> BetaKeyRecord:
    """Marks a beta API key as revoked."""

    records = load_records(store_path)
    for index, record in enumerate(records):
        if record.key_id == key_id:
            revoked = BetaKeyRecord(
                key_id=record.key_id,
                owner_name=record.owner_name,
                contact=record.contact,
                api_key=record.api_key,
                status="revoked",
                created_at=record.created_at,
                revoked_at=utc_now(),
                note=record.note,
                host_client=record.host_client,
            )
            records[index] = revoked
            save_records(store_path, records)
            return revoked
    raise KeyError(f"Unknown key_id: {key_id}")


def list_keys(
    *,
    store_path: Path,
    status: Literal["active", "revoked", "all"] = "active",
) -> list[BetaKeyRecord]:
    """Returns beta keys filtered by status."""

    records = load_records(store_path)
    if status == "all":
        return records
    return [record for record in records if record.status == status]


def render_env_value(store_path: Path) -> str:
    """Renders active keys into the env var format expected by the cloud service."""

    active_keys = [record.api_key for record in list_keys(store_path=store_path, status="active")]
    return ",".join(active_keys)


def render_install_command(
    *,
    api_key: str,
    server_url: str = DEFAULT_SERVER_URL,
    host: str = "codex-cli",
) -> str:
    """Renders the beta user install command."""

    return (
        f"curl -fsSL {server_url}/install.sh | "
        f"bash -s -- --server-url {server_url} --api-key {api_key} --host {host}"
    )


def render_email_subject(record: BetaKeyRecord) -> str:
    """Renders a stable beta invitation subject line."""

    return f"MOE Toolkit Beta access for {record.owner_name}"


def render_email_body(record: BetaKeyRecord, *, server_url: str = DEFAULT_SERVER_URL) -> str:
    """Renders a user-facing beta invitation email body."""

    install_command = render_install_command(
        api_key=record.api_key,
        server_url=server_url,
        host=record.host_client,
    )
    return (
        f"{record.owner_name}，你好。\n\n"
        "MOE Toolkit Beta 已为你开通。\n\n"
        f"云端地址：\n{server_url}\n\n"
        f"你的 API Key：\n{record.api_key}\n\n"
        f"安装说明页：\n{server_url}/beta\n\n"
        "推荐安装命令：\n"
        f"{install_command}\n\n"
        "注意事项：\n"
        "- 当前为 Beta 版本，使用 HTTP + API Key，不建议处理高敏感数据。\n"
        "- 如需重新配置，可运行 `moe-connector configure`。\n"
        "- 如安装失败，请把终端输出回传给运营侧。\n"
    )


def filename_slug(value: str) -> str:
    """Converts a user-facing label into a filesystem-safe slug."""

    lowered = value.strip().lower()
    slug_chars = [char if char.isalnum() else "-" for char in lowered]
    slug = "".join(slug_chars).strip("-")
    return slug or "user"


def export_email_templates(
    *,
    records: list[BetaKeyRecord],
    output_dir: Path,
    server_url: str = DEFAULT_SERVER_URL,
) -> tuple[Path, Path]:
    """Writes per-user email templates and a CSV manifest."""

    output_dir.mkdir(parents=True, exist_ok=True)
    emails_dir = output_dir / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "email_manifest.csv"

    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "key_id",
                "owner_name",
                "contact",
                "status",
                "host_client",
                "subject",
                "template_path",
                "install_command",
            ],
        )
        writer.writeheader()
        for record in records:
            email_path = emails_dir / f"{record.key_id}-{filename_slug(record.owner_name)}.txt"
            email_path.write_text(render_email_body(record, server_url=server_url), encoding="utf-8")
            writer.writerow(
                {
                    "key_id": record.key_id,
                    "owner_name": record.owner_name,
                    "contact": record.contact,
                    "status": record.status,
                    "host_client": record.host_client,
                    "subject": render_email_subject(record),
                    "template_path": str(email_path),
                    "install_command": render_install_command(
                        api_key=record.api_key,
                        server_url=server_url,
                        host=record.host_client,
                    ),
                }
            )

    return emails_dir, manifest_path


def bulk_issue_from_csv(
    *,
    store_path: Path,
    csv_path: Path,
    output_dir: Path,
    server_url: str = DEFAULT_SERVER_URL,
    default_host: str = "codex-cli",
) -> tuple[list[BetaKeyRecord], Path, Path]:
    """Issues keys from a CSV and exports install/email materials."""

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Input CSV is missing a header row.")
        issued_records: list[BetaKeyRecord] = []
        for row_number, row in enumerate(reader, start=2):
            owner_name = (row.get("owner_name") or "").strip()
            if not owner_name:
                raise ValueError(f"Row {row_number} is missing owner_name.")
            issued_records.append(
                issue_key(
                    store_path=store_path,
                    owner_name=owner_name,
                    contact=(row.get("contact") or "").strip(),
                    note=(row.get("note") or "").strip(),
                    host_client=normalize_host(
                        row.get("host_client") or row.get("host"),
                        default_host=default_host,
                    ),
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    issued_csv_path = output_dir / "issued_keys.csv"
    with issued_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "key_id",
                "owner_name",
                "contact",
                "status",
                "created_at",
                "host_client",
                "note",
                "api_key",
                "install_command",
            ],
        )
        writer.writeheader()
        for record in issued_records:
            writer.writerow(
                {
                    "key_id": record.key_id,
                    "owner_name": record.owner_name,
                    "contact": record.contact,
                    "status": record.status,
                    "created_at": record.created_at,
                    "host_client": record.host_client,
                    "note": record.note,
                    "api_key": record.api_key,
                    "install_command": render_install_command(
                        api_key=record.api_key,
                        server_url=server_url,
                        host=record.host_client,
                    ),
                }
            )

    emails_dir, manifest_path = export_email_templates(
        records=issued_records,
        output_dir=output_dir,
        server_url=server_url,
    )
    return issued_records, issued_csv_path, manifest_path


def filter_records(
    *,
    records: list[BetaKeyRecord],
    status: Literal["active", "revoked", "all"] = "active",
    key_ids: set[str] | None = None,
) -> list[BetaKeyRecord]:
    """Filters records by status and optional key ids."""

    filtered = records if status == "all" else [record for record in records if record.status == status]
    if key_ids:
        filtered = [record for record in filtered if record.key_id in key_ids]
    return filtered


def build_parser() -> argparse.ArgumentParser:
    """Builds the beta admin CLI parser."""

    parser = argparse.ArgumentParser(prog="moe-beta-admin")
    parser.add_argument("--store-path", default=str(DEFAULT_STORE_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue = subparsers.add_parser("issue")
    issue.add_argument("--owner-name", required=True)
    issue.add_argument("--contact", default="")
    issue.add_argument("--note", default="")
    issue.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    issue.add_argument("--host", choices=SUPPORTED_HOSTS, default="codex-cli")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status", choices=["active", "revoked", "all"], default="active")

    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--key-id", required=True)

    render_env = subparsers.add_parser("render-env")
    render_env.add_argument("--prefix", action="store_true")

    bulk_issue = subparsers.add_parser("bulk-issue")
    bulk_issue.add_argument("--input-csv", required=True)
    bulk_issue.add_argument("--output-dir", required=True)
    bulk_issue.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    bulk_issue.add_argument("--default-host", choices=SUPPORTED_HOSTS, default="codex-cli")

    export_emails = subparsers.add_parser("export-emails")
    export_emails.add_argument("--output-dir", required=True)
    export_emails.add_argument("--status", choices=["active", "revoked", "all"], default="active")
    export_emails.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    export_emails.add_argument("--key-id", action="append", default=[])

    return parser


def cmd_issue(args: argparse.Namespace) -> int:
    """Handles beta key issuance."""

    record = issue_key(
        store_path=Path(args.store_path),
        owner_name=args.owner_name,
        contact=args.contact,
        note=args.note,
        host_client=args.host,
    )
    print(f"key_id={record.key_id}")
    print(f"owner_name={record.owner_name}")
    print(f"api_key={record.api_key}")
    print(f"status={record.status}")
    print(f"created_at={record.created_at}")
    print(f"host_client={record.host_client}")
    if record.contact:
        print(f"contact={record.contact}")
    if record.note:
        print(f"note={record.note}")
    print("install_command:")
    print(
        render_install_command(
            api_key=record.api_key,
            server_url=args.server_url,
            host=args.host,
        )
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Lists issued beta keys."""

    records = list_keys(
        store_path=Path(args.store_path),
        status=args.status,
    )
    for record in records:
        print(
            "\t".join(
                [
                    record.key_id,
                    record.status,
                    record.owner_name,
                    record.contact or "-",
                    record.host_client,
                    record.created_at,
                    record.revoked_at or "-",
                ]
            )
        )
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    """Revokes a beta key."""

    record = revoke_key(store_path=Path(args.store_path), key_id=args.key_id)
    print(f"revoked key_id={record.key_id}")
    print(f"api_key={record.api_key}")
    print(f"revoked_at={record.revoked_at}")
    return 0


def cmd_render_env(args: argparse.Namespace) -> int:
    """Prints the env var value for active beta keys."""

    value = render_env_value(Path(args.store_path))
    if args.prefix:
        print(f"MOE_API_KEYS_RAW={value}")
    else:
        print(value)
    return 0


def cmd_bulk_issue(args: argparse.Namespace) -> int:
    """Issues keys in bulk from a CSV file."""

    records, issued_csv_path, manifest_path = bulk_issue_from_csv(
        store_path=Path(args.store_path),
        csv_path=Path(args.input_csv),
        output_dir=Path(args.output_dir),
        server_url=args.server_url,
        default_host=args.default_host,
    )
    print(f"issued_count={len(records)}")
    print(f"issued_csv={issued_csv_path}")
    print(f"email_manifest={manifest_path}")
    print(f"emails_dir={Path(args.output_dir) / 'emails'}")
    return 0


def cmd_export_emails(args: argparse.Namespace) -> int:
    """Exports email templates for existing beta keys."""

    records = filter_records(
        records=load_records(Path(args.store_path)),
        status=args.status,
        key_ids=set(args.key_id),
    )
    emails_dir, manifest_path = export_email_templates(
        records=records,
        output_dir=Path(args.output_dir),
        server_url=args.server_url,
    )
    print(f"exported_count={len(records)}")
    print(f"email_manifest={manifest_path}")
    print(f"emails_dir={emails_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for beta key operations."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "issue":
        return cmd_issue(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "revoke":
        return cmd_revoke(args)
    if args.command == "render-env":
        return cmd_render_env(args)
    if args.command == "bulk-issue":
        return cmd_bulk_issue(args)
    if args.command == "export-emails":
        return cmd_export_emails(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
