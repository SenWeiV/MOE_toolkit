"""Cloud API entrypoint."""

from __future__ import annotations

import uvicorn

from moe_toolkit.cloud.app import create_app
from moe_toolkit.cloud.settings import CloudSettings


def main() -> None:
    """Runs the FastAPI server with configured settings."""

    settings = CloudSettings()
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
    )


if __name__ == "__main__":
    main()

