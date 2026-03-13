from __future__ import annotations

import json

from moe_toolkit.cloud.registry import CuratedRegistry, default_registry_root


def test_default_registry_root_prefers_cwd_tools_directory(tmp_path, monkeypatch) -> None:
    manifest_dir = tmp_path / "tools" / "curated" / "demo"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps(
            {
                "tool_id": "demo-tool",
                "version": "0.1.0",
                "description": "demo",
                "capabilities": ["demo"],
                "input_types": ["csv"],
                "output_types": ["json"],
                "image": "moe-tool-demo",
                "network_required": False,
                "enabled": True,
                "priority": 10,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert default_registry_root() == tmp_path / "tools" / "curated"
    registry = CuratedRegistry()
    summaries = registry.summaries()
    assert len(summaries) == 1
    assert summaries[0].tool_id == "demo-tool"
