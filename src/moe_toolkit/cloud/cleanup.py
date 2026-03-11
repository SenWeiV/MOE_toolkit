"""Filesystem cleanup helpers for the MOE cloud runtime."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from moe_toolkit.schemas.common import UploadRef


@dataclass(slots=True)
class CleanupReport:
    """Summarizes a cleanup cycle."""

    scanned_upload_dirs: int = 0
    removed_upload_dirs: int = 0
    skipped_upload_dirs: int = 0


def cleanup_expired_uploads(
    storage_root: Path,
    *,
    now: datetime | None = None,
) -> CleanupReport:
    """Deletes upload directories whose metadata is already expired."""

    report = CleanupReport()
    uploads_root = storage_root / "uploads"
    if not uploads_root.exists():
        return report

    current_time = now or datetime.now(UTC)
    for upload_dir in sorted(path for path in uploads_root.iterdir() if path.is_dir()):
        report.scanned_upload_dirs += 1
        metadata_path = upload_dir / "metadata.json"
        if not metadata_path.exists():
            report.skipped_upload_dirs += 1
            continue

        upload_ref = UploadRef.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        if upload_ref.expires_at > current_time:
            report.skipped_upload_dirs += 1
            continue

        shutil.rmtree(upload_dir)
        report.removed_upload_dirs += 1

    return report
