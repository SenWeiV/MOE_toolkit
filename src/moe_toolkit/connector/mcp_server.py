"""FastMCP server exposed by the local connector."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from moe_toolkit.connector.client import CloudClient
from moe_toolkit.connector.config import DEFAULT_CONFIG_PATH, load_config, save_config
from moe_toolkit.schemas.common import ConnectorConfig


def build_server(config_path: Path = DEFAULT_CONFIG_PATH) -> FastMCP:
    """Builds the stdio MCP server for the connector."""

    server = FastMCP("moe-toolkit")

    @server.tool(name="service.health")
    async def service_health() -> dict[str, object]:
        """Returns current cloud health status."""

        config = load_config(config_path)
        client = CloudClient(config)
        health = await client.get_health()
        return health.model_dump(mode="json")

    @server.tool(name="service.configure")
    async def service_configure(
        server_url: str,
        api_key: str,
        output_dir: str | None = None,
        host_client: str = "codex-cli",
    ) -> dict[str, str]:
        """Updates local connector configuration."""

        current = ConnectorConfig(
            server_url=server_url,
            api_key=api_key,
            output_dir=Path(output_dir) if output_dir else Path.home() / "MOE Outputs",
            host_client=host_client,
            run_poll_interval_seconds=0.1,
        )
        saved_path = save_config(current, config_path=config_path)
        return {
            "status": "configured",
            "config_path": str(saved_path),
        }

    @server.tool(name="task.execute")
    async def task_execute(
        task: str,
        attachments: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Uploads local files, executes the remote task, and downloads artifacts."""

        config = load_config(config_path)
        client = CloudClient(config)
        uploaded = []
        for attachment in attachments or []:
            uploaded.append(await client.upload_file(Path(attachment)))
        accepted = await client.execute_task(
            task=task,
            attachments=[item.upload_id for item in uploaded],
            session_id=session_id,
        )
        run = await client.wait_for_run(accepted.run_id)
        artifacts = await client.get_artifacts(accepted.run_id)
        downloaded_paths = [
            str(await client.download_artifact(artifact, config.output_dir))
            for artifact in artifacts
        ]
        return {
            "status": run.status,
            "run_id": run.run_id,
            "route_plan": run.route_plan.model_dump(mode="json"),
            "downloaded_paths": downloaded_paths,
        }

    @server.tool(name="run.get_status")
    async def run_get_status(run_id: str) -> dict[str, object]:
        """Fetches the remote run status."""

        config = load_config(config_path)
        client = CloudClient(config)
        run = await client.get_run(run_id)
        return run.model_dump(mode="json")

    @server.tool(name="run.get_artifacts")
    async def run_get_artifacts(run_id: str) -> dict[str, object]:
        """Lists and downloads run artifacts."""

        config = load_config(config_path)
        client = CloudClient(config)
        artifacts = await client.get_artifacts(run_id)
        downloaded_paths = [
            str(await client.download_artifact(artifact, config.output_dir))
            for artifact in artifacts
        ]
        return {
            "run_id": run_id,
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
            "downloaded_paths": downloaded_paths,
        }

    return server


def run_server(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Runs the connector MCP server over stdio."""

    build_server(config_path).run()
