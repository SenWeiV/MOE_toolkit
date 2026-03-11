from __future__ import annotations

import csv
import json
from pathlib import Path


def find_numeric_columns(rows: list[dict[str, str]], fieldnames: list[str]) -> list[str]:
    numeric_columns: list[str] = []
    for field in fieldnames:
        values = [row.get(field, "").strip() for row in rows if row.get(field, "").strip()]
        if values:
            try:
                for value in values[:20]:
                    float(value)
            except ValueError:
                continue
            numeric_columns.append(field)
    return numeric_columns


def main() -> None:
    run_spec = json.loads(Path("/work/run.json").read_text(encoding="utf-8"))
    task = run_spec["task"]
    artifacts_dir = Path("/work/artifacts")
    input_dir = Path("/work/inputs")
    for attachment in run_spec["attachments"]:
        source = input_dir / attachment["workspace_name"]
        delimiter = "\t" if source.suffix.lower() == ".tsv" else ","
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
        summary = {
            "source": source.name,
            "rows": len(rows),
            "columns": fieldnames,
            "numeric_columns": find_numeric_columns(rows, fieldnames),
            "task": task,
        }
        (artifacts_dir / f"{source.stem}-summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
