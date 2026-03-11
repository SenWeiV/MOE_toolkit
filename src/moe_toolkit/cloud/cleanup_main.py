"""Cleanup job entrypoint."""

from __future__ import annotations

import logging
import time

from moe_toolkit.cloud.cleanup import cleanup_expired_uploads
from moe_toolkit.cloud.settings import CloudSettings


def run_cleanup_cycle(settings: CloudSettings, logger: logging.Logger) -> None:
    """Runs one cleanup cycle and logs the result."""

    report = cleanup_expired_uploads(settings.storage_root)
    logger.info(
        "Cleanup cycle completed: scanned_upload_dirs=%s removed_upload_dirs=%s skipped_upload_dirs=%s",
        report.scanned_upload_dirs,
        report.removed_upload_dirs,
        report.skipped_upload_dirs,
    )


def main() -> None:
    """Runs the cleanup loop for expired uploads."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("moe.cleanup")
    settings = CloudSettings()
    logger.info("MOE cleanup job started for storage_root=%s", settings.storage_root)
    while True:
        run_cleanup_cycle(settings, logger)
        time.sleep(settings.cleanup_interval_seconds)


if __name__ == "__main__":
    main()
