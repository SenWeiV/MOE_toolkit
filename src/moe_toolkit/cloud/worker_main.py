"""Standalone worker entrypoint for processing queued runs."""

from __future__ import annotations

import asyncio
import logging

from moe_toolkit.cloud.executors import DockerExecutor, InlineExecutor
from moe_toolkit.cloud.services import CloudService
from moe_toolkit.cloud.settings import CloudSettings


async def run_worker(settings: CloudSettings) -> None:
    """Runs the shared queue worker loop."""

    if settings.execution_backend == "docker":
        executor = DockerExecutor(
            docker_binary=settings.docker_binary,
            storage_root=settings.storage_root,
            host_storage_root=settings.docker_host_storage_root,
            network_mode=settings.docker_network_mode,
        )
    else:
        executor = InlineExecutor()

    service = CloudService(
        storage_root=settings.storage_root,
        base_url=settings.public_base_url,
        executor=executor,
        embedded_worker_enabled=False,
        queue_poll_interval_seconds=settings.queue_poll_interval_seconds,
        queue_claim_timeout_seconds=settings.queue_claim_timeout_seconds,
    )
    logger = logging.getLogger("moe.worker")
    logger.info(
        "MOE worker started with storage_root=%s execution_backend=%s",
        settings.storage_root,
        settings.execution_backend,
    )
    while True:
        processed = await service.process_next_queued_run()
        if not processed:
            await asyncio.sleep(settings.queue_poll_interval_seconds)

def main() -> None:
    """Runs the standalone worker loop."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_worker(CloudSettings()))


if __name__ == "__main__":
    main()
