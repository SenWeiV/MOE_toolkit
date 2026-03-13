from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    run_root = Path("/work")
    run_spec = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    artifacts_dir = run_root / "artifacts"
    artifact_names = sorted(path.name for path in artifacts_dir.iterdir() if path.is_file())
    summary_sections: list[str] = []
    for artifact_name in artifact_names:
        if not artifact_name.endswith("-summary.json"):
            continue
        payload = json.loads((artifacts_dir / artifact_name).read_text(encoding="utf-8"))
        summary_sections.extend(
            [
                f"### {payload['source']}",
                f"- Rows: {payload['rows']}",
                f"- Columns: {', '.join(payload['columns'])}",
                f"- Numeric columns: {', '.join(payload['numeric_columns']) or 'None'}",
                "",
            ]
        )

    lines = [
        "# MOE Toolkit Run Report",
        "",
        f"- Run ID: {run_spec['run_id']}",
        f"- Task: {run_spec['task']}",
        "",
        "## Attachments",
    ]
    for attachment in run_spec["attachments"]:
        lines.append(f"- {attachment['source_name']} -> {attachment['workspace_name']}")

    lines.extend(["", "## Artifacts"])
    for artifact_name in artifact_names:
        lines.append(f"- {artifact_name}")

    if summary_sections:
        lines.extend(["", "## Summaries", ""])
        lines.extend(summary_sections)

    (artifacts_dir / "run-report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
