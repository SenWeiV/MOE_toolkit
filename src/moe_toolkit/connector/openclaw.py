"""OpenClaw workspace discovery and host integration helpers."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Callable, Mapping

from moe_toolkit.schemas.common import HostInstallResult

OPENCLAW_WORKSPACE_ENV = "OPENCLAW_WORKSPACE"
OPENCLAW_CONFIG_ENV = "OPENCLAW_CONFIG_PATH"
OPENCLAW_MARKER_START = "<!-- MOE_TOOLKIT_OPENCLAW_START -->"
OPENCLAW_MARKER_END = "<!-- MOE_TOOLKIT_OPENCLAW_END -->"
OPENCLAW_BOOTSTRAP_FILES = ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md")
OPENCLAW_WRAPPER_RELATIVE_PATH = Path(".moe-toolkit") / "bin" / "moe-openclaw"
OPENCLAW_OUTPUT_DIR_NAME = "MOE Outputs"


class OpenClawWorkspaceError(RuntimeError):
    """Raised when OpenClaw workspace discovery or validation fails."""


def canonicalize_path(path: Path) -> Path:
    """Expands and normalizes a path without requiring it to exist."""

    return path.expanduser().resolve(strict=False)


def get_default_openclaw_config_path(home: Path | None = None) -> Path:
    """Returns the default OpenClaw config path."""

    return (home or Path.home()) / ".openclaw" / "openclaw.json"


def get_tools_path(workspace_path: Path) -> Path:
    """Returns the OpenClaw workspace TOOLS.md path."""

    return workspace_path / "TOOLS.md"


def get_wrapper_path(workspace_path: Path) -> Path:
    """Returns the OpenClaw workspace wrapper path."""

    return workspace_path / OPENCLAW_WRAPPER_RELATIVE_PATH


def get_output_dir(workspace_path: Path) -> Path:
    """Returns the OpenClaw workspace output directory."""

    return workspace_path / OPENCLAW_OUTPUT_DIR_NAME


def is_bootstrapped_workspace(workspace_path: Path) -> bool:
    """Checks whether a directory looks like an initialized OpenClaw workspace."""

    return workspace_path.is_dir() and any(
        (workspace_path / filename).exists() for filename in OPENCLAW_BOOTSTRAP_FILES
    )


def is_installed_workspace(workspace_path: Path) -> bool:
    """Checks whether the MOE OpenClaw integration is installed in a workspace."""

    tools_path = get_tools_path(workspace_path)
    wrapper_path = get_wrapper_path(workspace_path)
    if not tools_path.exists() or not wrapper_path.exists():
        return False
    return OPENCLAW_MARKER_START in tools_path.read_text(encoding="utf-8")


def load_workspace_from_config(config_path: Path) -> Path | None:
    """Loads the default OpenClaw workspace path from a JSON config file."""

    if not config_path.exists():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    workspace = payload.get("agents", {}).get("defaults", {}).get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        return None
    return canonicalize_path(Path(workspace))


def discover_workspaces(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    """Discovers candidate OpenClaw workspaces from env, config, and default dirs."""

    resolved_home = home or Path.home()
    env_map = env or {}
    seen: set[Path] = set()
    discovered: list[Path] = []

    def maybe_add(candidate: Path | None) -> None:
        if candidate is None:
            return
        normalized = canonicalize_path(candidate)
        if normalized in seen or not normalized.is_dir():
            return
        if not is_bootstrapped_workspace(normalized):
            return
        seen.add(normalized)
        discovered.append(normalized)

    workspace_from_env = env_map.get(OPENCLAW_WORKSPACE_ENV)
    if workspace_from_env:
        maybe_add(Path(workspace_from_env))

    config_env_path = env_map.get(OPENCLAW_CONFIG_ENV)
    if config_env_path:
        maybe_add(load_workspace_from_config(canonicalize_path(Path(config_env_path))))

    maybe_add(load_workspace_from_config(get_default_openclaw_config_path(resolved_home)))

    openclaw_home = resolved_home / ".openclaw"
    if openclaw_home.exists():
        for candidate in sorted(openclaw_home.glob("workspace-*")):
            maybe_add(candidate)

    return discovered


def _choose_workspace_interactively(
    candidates: list[Path],
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> Path:
    if len(candidates) == 1:
        candidate = candidates[0]
        answer = input_fn(f"Use OpenClaw workspace {candidate}? [Y/n]: ").strip().lower()
        if answer in {"", "y", "yes"}:
            return candidate
        manual = input_fn("Enter the OpenClaw workspace path: ").strip()
        if not manual:
            raise OpenClawWorkspaceError("No OpenClaw workspace path provided.")
        return validate_workspace(Path(manual))

    print_fn("Discovered OpenClaw workspaces:")
    for index, candidate in enumerate(candidates, start=1):
        print_fn(f"  {index}. {candidate}")
    answer = input_fn("Select a workspace number or enter an absolute path: ").strip()
    if not answer:
        raise OpenClawWorkspaceError("No OpenClaw workspace selected.")
    if answer.isdigit():
        selected_index = int(answer) - 1
        if 0 <= selected_index < len(candidates):
            return candidates[selected_index]
        raise OpenClawWorkspaceError("OpenClaw workspace selection is out of range.")
    return validate_workspace(Path(answer))


def validate_workspace(workspace_path: Path) -> Path:
    """Normalizes and validates an OpenClaw workspace path."""

    normalized = canonicalize_path(workspace_path)
    if not normalized.exists() or not normalized.is_dir():
        raise OpenClawWorkspaceError(f"OpenClaw workspace not found: {normalized}")
    if not is_bootstrapped_workspace(normalized):
        raise OpenClawWorkspaceError(
            "OpenClaw workspace is not bootstrapped yet. Start the target agent once before installing MOE."
        )
    return normalized


def resolve_workspace(
    *,
    workspace_path: Path | None = None,
    require_installed: bool = False,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    is_tty: bool | None = None,
) -> Path:
    """Resolves the OpenClaw workspace using explicit path or interactive discovery."""

    if workspace_path is not None:
        normalized = validate_workspace(workspace_path)
        if require_installed and not is_installed_workspace(normalized):
            raise OpenClawWorkspaceError(
                f"MOE OpenClaw integration is not installed in workspace: {normalized}"
            )
        return normalized

    discovered = discover_workspaces(home=home, env=env)
    if require_installed:
        discovered = [candidate for candidate in discovered if is_installed_workspace(candidate)]
    if not discovered:
        if require_installed:
            raise OpenClawWorkspaceError(
                "No OpenClaw workspace with MOE integration was found. Re-run with --workspace-path."
            )
        raise OpenClawWorkspaceError(
            "No bootstrapped OpenClaw workspace was found. Start the target agent once or pass --workspace-path."
        )

    interactive = is_tty if is_tty is not None else (sys.stdin.isatty() and sys.stdout.isatty())
    if not interactive:
        raise OpenClawWorkspaceError(
            "OpenClaw workspace discovery needs confirmation. Re-run with --workspace-path."
        )
    return _choose_workspace_interactively(discovered, input_fn=input_fn, print_fn=print_fn)


def build_tools_block(*, workspace_path: Path) -> str:
    """Builds the managed TOOLS.md block for OpenClaw."""

    wrapper_path = get_wrapper_path(workspace_path)
    output_dir = get_output_dir(workspace_path)
    return "\n".join(
        [
            OPENCLAW_MARKER_START,
            "## MOE Toolkit",
            "",
            "- Use MOE Toolkit for remote CSV, table, and chart workflows.",
            f"- Command entry: `{wrapper_path}`",
            "- Invoke it with:",
            f"  `{wrapper_path} --task \"<task>\" --attach \"<workspace-relative-file>\"`",
            "- Repeat `--attach` for more workspace-local files.",
            "- Only pass files that stay inside this workspace.",
            f"- Generated artifacts download to `{output_dir}`.",
            "- Read the returned JSON and continue from the listed `downloaded_paths`.",
            OPENCLAW_MARKER_END,
            "",
        ]
    )


def remove_tools_block(content: str) -> str:
    """Removes the managed MOE block from TOOLS.md content."""

    if OPENCLAW_MARKER_START not in content:
        return content
    start = content.index(OPENCLAW_MARKER_START)
    end = content.index(OPENCLAW_MARKER_END, start) + len(OPENCLAW_MARKER_END)
    before = content[:start].rstrip()
    after = content[end:].lstrip("\n")
    if before and after:
        return before + "\n\n" + after
    if before:
        return before + "\n"
    return after


def upsert_tools_block(content: str, *, workspace_path: Path) -> str:
    """Upserts the managed MOE block into TOOLS.md content."""

    managed_block = build_tools_block(workspace_path=workspace_path).strip()
    cleaned = remove_tools_block(content).strip()
    if cleaned:
        return cleaned + "\n\n" + managed_block + "\n"
    return managed_block + "\n"


def build_wrapper_script(
    *,
    workspace_path: Path,
    connector_command: str,
    connector_config_path: Path | None = None,
) -> str:
    """Builds the workspace-local OpenClaw wrapper script."""

    command_parts = [
        shlex.quote(connector_command),
        "openclaw",
        "run",
        "--workspace-path",
        shlex.quote(str(workspace_path)),
    ]
    if connector_config_path is not None:
        command_parts.extend(["--config-path", shlex.quote(str(connector_config_path))])
    command = " ".join(command_parts)
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            'if [[ $# -eq 0 ]]; then',
            '  echo "Usage: moe-openclaw --task \\"<task>\\" [--attach <path>] [--session-id <id>]" >&2',
            "  exit 1",
            "fi",
            f"exec {command} \"$@\"",
            "",
        ]
    )


def resolve_attachment_path(workspace_path: Path, raw_path: str) -> Path:
    """Ensures an attachment path stays inside the selected OpenClaw workspace."""

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_path / candidate
    resolved_workspace = canonicalize_path(workspace_path)
    resolved_candidate = candidate.resolve(strict=True)
    if resolved_candidate != resolved_workspace and resolved_workspace not in resolved_candidate.parents:
        raise OpenClawWorkspaceError(
            f"Attachment must stay inside the OpenClaw workspace: {raw_path}"
        )
    if not resolved_candidate.is_file():
        raise OpenClawWorkspaceError(f"Attachment must be a file: {resolved_candidate}")
    return resolved_candidate


class OpenClawHostAdapter:
    """Installs and removes the MOE wrapper from an OpenClaw workspace."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = validate_workspace(workspace_path)
        self.tools_path = get_tools_path(self.workspace_path)
        self.wrapper_path = get_wrapper_path(self.workspace_path)

    def install(
        self,
        *,
        connector_command: str = "moe-connector",
        connector_config_path: Path | None = None,
    ) -> HostInstallResult:
        existing_tools = self.tools_path.read_text(encoding="utf-8") if self.tools_path.exists() else ""
        updated_tools = upsert_tools_block(existing_tools, workspace_path=self.workspace_path)
        wrapper_content = build_wrapper_script(
            workspace_path=self.workspace_path,
            connector_command=connector_command,
            connector_config_path=connector_config_path,
        )
        existing_wrapper = self.wrapper_path.read_text(encoding="utf-8") if self.wrapper_path.exists() else ""
        tools_changed = updated_tools != existing_tools
        wrapper_changed = wrapper_content != existing_wrapper

        self.tools_path.parent.mkdir(parents=True, exist_ok=True)
        self.wrapper_path.parent.mkdir(parents=True, exist_ok=True)
        self.tools_path.write_text(updated_tools, encoding="utf-8")
        self.wrapper_path.write_text(wrapper_content, encoding="utf-8")
        self.wrapper_path.chmod(0o755)

        return HostInstallResult(
            host="openclaw",
            config_path=self.tools_path,
            changed=tools_changed or wrapper_changed,
            detail="OpenClaw workspace integration installed",
        )

    def is_installed(self) -> bool:
        return is_installed_workspace(self.workspace_path)

    def uninstall(self) -> HostInstallResult:
        existing_tools = self.tools_path.read_text(encoding="utf-8") if self.tools_path.exists() else ""
        updated_tools = remove_tools_block(existing_tools)
        tools_changed = updated_tools != existing_tools
        wrapper_changed = self.wrapper_path.exists()

        if self.tools_path.exists() or tools_changed:
            if updated_tools.strip():
                self.tools_path.write_text(updated_tools.rstrip() + "\n", encoding="utf-8")
            else:
                self.tools_path.parent.mkdir(parents=True, exist_ok=True)
                self.tools_path.write_text("", encoding="utf-8")
        if self.wrapper_path.exists():
            self.wrapper_path.unlink()
        for candidate in [self.wrapper_path.parent, self.wrapper_path.parent.parent]:
            if candidate.exists() and not any(candidate.iterdir()):
                candidate.rmdir()

        return HostInstallResult(
            host="openclaw",
            config_path=self.tools_path,
            changed=tools_changed or wrapper_changed,
            detail="OpenClaw workspace integration removed",
        )
