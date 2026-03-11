from __future__ import annotations

import csv
import json
from pathlib import Path


def build_svg_chart(rows: list[dict[str, str]], field: str) -> str:
    values = [float(row[field]) for row in rows if row.get(field, "").strip()]
    if not values:
        values = [0.0]
    max_value = max(values) or 1.0
    points: list[str] = []
    width = 480
    height = 240
    for index, value in enumerate(values):
        x = 20 + (index * (width - 40) / max(len(values) - 1, 1))
        y = height - 20 - (value / max_value) * (height - 40)
        points.append(f"{x:.2f},{y:.2f}")
    polyline = " ".join(points)
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="240">',
            '<rect width="100%" height="100%" fill="white" />',
            f'<text x="20" y="24" font-size="16">MOE Preview Chart: {field}</text>',
            f'<polyline fill="none" stroke="#2563eb" stroke-width="2" points="{polyline}" />',
            "</svg>",
            "",
        ]
    )


def main() -> None:
    run_spec = json.loads(Path("/work/run.json").read_text(encoding="utf-8"))
    task = run_spec["task"].lower()
    if not any(token in task for token in ["图", "chart", "plot", "trend", "趋势"]):
        return

    artifacts_dir = Path("/work/artifacts")
    input_dir = Path("/work/inputs")
    for attachment in run_spec["attachments"]:
        source = input_dir / attachment["workspace_name"]
        delimiter = "\t" if source.suffix.lower() == ".tsv" else ","
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
        numeric_columns = []
        for field in fieldnames:
            values = [row.get(field, "").strip() for row in rows if row.get(field, "").strip()]
            if not values:
                continue
            try:
                for value in values[:20]:
                    float(value)
            except ValueError:
                continue
            numeric_columns.append(field)
        if numeric_columns:
            (artifacts_dir / f"{source.stem}-chart.svg").write_text(
                build_svg_chart(rows, numeric_columns[0]),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
