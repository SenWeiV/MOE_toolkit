from __future__ import annotations

from datetime import UTC, datetime, timedelta

from moe_toolkit.cloud.cleanup import cleanup_expired_uploads
from moe_toolkit.cloud.executors import InlineExecutor
from moe_toolkit.cloud.services import CloudService
from moe_toolkit.schemas.common import UploadRef


def test_save_upload_persists_metadata_file(tmp_path) -> None:
    service = CloudService(
        storage_root=tmp_path,
        base_url="http://testserver",
        executor=InlineExecutor(),
    )

    upload = service.save_upload(
        filename="sales.csv",
        content_type="text/csv",
        payload=b"month,value\n1,10\n",
    )

    metadata_path = tmp_path / "uploads" / upload.upload_id / "metadata.json"
    assert metadata_path.exists()
    persisted = UploadRef.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    assert persisted.upload_id == upload.upload_id
    assert persisted.filename == "sales.csv"


def test_cleanup_expired_uploads_removes_only_expired_directories(tmp_path) -> None:
    uploads_root = tmp_path / "uploads"
    expired_dir = uploads_root / "expired"
    active_dir = uploads_root / "active"
    expired_dir.mkdir(parents=True)
    active_dir.mkdir(parents=True)
    (expired_dir / "sales.csv").write_text("month,value\n1,10\n", encoding="utf-8")
    (active_dir / "sales.csv").write_text("month,value\n1,20\n", encoding="utf-8")

    expired_ref = UploadRef(
        upload_id="expired",
        filename="sales.csv",
        size_bytes=18,
        content_type="text/csv",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    active_ref = UploadRef(
        upload_id="active",
        filename="sales.csv",
        size_bytes=18,
        content_type="text/csv",
        expires_at=datetime.now(UTC) + timedelta(minutes=55),
    )
    (expired_dir / "metadata.json").write_text(
        expired_ref.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (active_dir / "metadata.json").write_text(
        active_ref.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    report = cleanup_expired_uploads(tmp_path, now=datetime.now(UTC))

    assert report.scanned_upload_dirs == 2
    assert report.removed_upload_dirs == 1
    assert report.skipped_upload_dirs == 1
    assert not expired_dir.exists()
    assert active_dir.exists()


def test_cleanup_expired_uploads_returns_empty_report_for_missing_root(tmp_path) -> None:
    report = cleanup_expired_uploads(tmp_path)

    assert report.scanned_upload_dirs == 0
    assert report.removed_upload_dirs == 0
    assert report.skipped_upload_dirs == 0


def test_cleanup_expired_uploads_skips_directories_without_metadata(tmp_path) -> None:
    orphan_dir = tmp_path / "uploads" / "orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "sales.csv").write_text("month,value\n1,10\n", encoding="utf-8")

    report = cleanup_expired_uploads(tmp_path, now=datetime.now(UTC))

    assert report.scanned_upload_dirs == 1
    assert report.removed_upload_dirs == 0
    assert report.skipped_upload_dirs == 1
    assert orphan_dir.exists()
