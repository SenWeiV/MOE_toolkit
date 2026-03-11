from __future__ import annotations

from pathlib import Path

import pytest

from moe_toolkit.connector.openclaw import (
    OPENCLAW_MARKER_START,
    OpenClawHostAdapter,
    OpenClawWorkspaceError,
    discover_workspaces,
    get_output_dir,
    get_tools_path,
    get_wrapper_path,
    resolve_attachment_path,
    resolve_workspace,
)


def bootstrap_workspace(path: Path, *, include_tools: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    if include_tools:
        (path / "TOOLS.md").write_text("# User Tools\n", encoding="utf-8")
    return path


def test_openclaw_adapter_install_and_uninstall_preserves_user_tools(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace")
    adapter = OpenClawHostAdapter(workspace)

    install_result = adapter.install(
        connector_command="/Users/demo/.local/bin/moe-connector",
        connector_config_path=Path("/Users/demo/.moe-connector/config.toml"),
    )
    installed_tools = get_tools_path(workspace).read_text(encoding="utf-8")
    wrapper_path = get_wrapper_path(workspace)

    assert install_result.changed is True
    assert adapter.is_installed() is True
    assert "# User Tools" in installed_tools
    assert OPENCLAW_MARKER_START in installed_tools
    assert str(wrapper_path) in installed_tools
    assert wrapper_path.exists()
    assert wrapper_path.stat().st_mode & 0o111

    uninstall_result = adapter.uninstall()
    removed_tools = get_tools_path(workspace).read_text(encoding="utf-8")

    assert uninstall_result.changed is True
    assert adapter.is_installed() is False
    assert removed_tools == "# User Tools\n"
    assert wrapper_path.exists() is False


def test_openclaw_uninstall_keeps_tools_file_when_only_managed_block_existed(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace", include_tools=False)
    adapter = OpenClawHostAdapter(workspace)

    adapter.install(
        connector_command="/Users/demo/.local/bin/moe-connector",
        connector_config_path=Path("/Users/demo/.moe-connector/config.toml"),
    )
    adapter.uninstall()

    assert get_tools_path(workspace).exists()
    assert get_tools_path(workspace).read_text(encoding="utf-8") == ""


def test_discover_workspaces_collects_env_config_and_default_dirs(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env_workspace = bootstrap_workspace(home / "env-workspace")
    config_workspace = bootstrap_workspace(home / "config-workspace")
    glob_workspace = bootstrap_workspace(home / ".openclaw" / "workspace-main")
    config_path = home / ".openclaw" / "openclaw.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        '{"agents":{"defaults":{"workspace":"' + str(config_workspace) + '"}}}\n',
        encoding="utf-8",
    )

    discovered = discover_workspaces(
        home=home,
        env={
            "OPENCLAW_WORKSPACE": str(env_workspace),
            "OPENCLAW_CONFIG_PATH": str(config_path),
        },
    )

    assert discovered == [env_workspace.resolve(), config_workspace.resolve(), glob_workspace.resolve()]


def test_resolve_workspace_requires_tty_for_discovery(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = bootstrap_workspace(home / ".openclaw" / "workspace-main")

    with pytest.raises(OpenClawWorkspaceError, match="needs confirmation"):
        resolve_workspace(home=home, is_tty=False)

    resolved = resolve_workspace(
        home=home,
        is_tty=True,
        input_fn=lambda prompt: "",
        print_fn=lambda message: None,
    )

    assert resolved == workspace.resolve()


def test_resolve_workspace_supports_number_selection(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = bootstrap_workspace(home / ".openclaw" / "workspace-alpha")
    second = bootstrap_workspace(home / ".openclaw" / "workspace-beta")

    resolved = resolve_workspace(
        home=home,
        is_tty=True,
        input_fn=lambda prompt: "2",
        print_fn=lambda message: None,
    )

    assert resolved == second.resolve()
    assert first.exists()


def test_resolve_attachment_path_rejects_workspace_escape(tmp_path: Path) -> None:
    workspace = bootstrap_workspace(tmp_path / "workspace")
    source = workspace / "sales.csv"
    source.write_text("month,value\n1,10\n", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("x,y\n1,2\n", encoding="utf-8")

    resolved = resolve_attachment_path(workspace, "sales.csv")

    assert resolved == source.resolve()

    with pytest.raises(OpenClawWorkspaceError, match="must stay inside"):
        resolve_attachment_path(workspace, str(outside))

    with pytest.raises(OpenClawWorkspaceError, match="must be a file"):
        resolve_attachment_path(workspace, ".")

    assert get_output_dir(workspace) == workspace / "MOE Outputs"
