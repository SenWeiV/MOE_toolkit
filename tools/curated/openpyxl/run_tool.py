from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook


def load_rows(source: Path) -> tuple[list[str], list[dict[str, str]]]:
    suffix = source.suffix.lower()
    if suffix == ".xlsx":
        workbook = load_workbook(source, read_only=True, data_only=True)
        sheet = workbook.active
        raw_rows = list(sheet.iter_rows(values_only=True))
        if not raw_rows:
            return [], []
        fieldnames = [str(value or "").strip() for value in raw_rows[0]]
        rows: list[dict[str, str]] = []
        for raw_row in raw_rows[1:]:
            row = {
                fieldnames[index]: "" if value is None else str(value)
                for index, value in enumerate(raw_row)
                if index < len(fieldnames) and fieldnames[index]
            }
            if row:
                rows.append(row)
        return fieldnames, rows

    delimiter = "\t" if suffix == ".tsv" else ","
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        return reader.fieldnames or [], rows


def find_numeric_columns(rows: list[dict[str, str]], fieldnames: list[str]) -> list[str]:
    numeric_columns: list[str] = []
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
    return numeric_columns


def write_report_workbook(
    *,
    artifacts_dir: Path,
    source: Path,
    task: str,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    numeric_columns: list[str],
) -> None:
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "summary"
    summary_sheet.append(["source", source.name])
    summary_sheet.append(["task", task])
    summary_sheet.append(["rows", len(rows)])
    summary_sheet.append(["columns", ", ".join(fieldnames)])
    summary_sheet.append(["numeric_columns", ", ".join(numeric_columns)])

    data_sheet = workbook.create_sheet("data")
    if fieldnames:
        data_sheet.append(fieldnames)
    for row in rows:
        data_sheet.append([row.get(field, "") for field in fieldnames])

    workbook.save(artifacts_dir / f"{source.stem}-report.xlsx")


def main() -> None:
    run_spec = json.loads(Path("/work/run.json").read_text(encoding="utf-8"))
    task = run_spec["task"]
    artifacts_dir = Path("/work/artifacts")
    input_dir = Path("/work/inputs")
    for attachment in run_spec["attachments"]:
        source = input_dir / attachment["workspace_name"]
        fieldnames, rows = load_rows(source)
        numeric_columns = find_numeric_columns(rows, fieldnames)
        summary_path = artifacts_dir / f"{source.stem}-summary.json"
        if not summary_path.exists():
            summary_path.write_text(
                json.dumps(
                    {
                        "source": source.name,
                        "rows": len(rows),
                        "columns": fieldnames,
                        "numeric_columns": numeric_columns,
                        "task": task,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        write_report_workbook(
            artifacts_dir=artifacts_dir,
            source=source,
            task=task,
            fieldnames=fieldnames,
            rows=rows,
            numeric_columns=numeric_columns,
        )


if __name__ == "__main__":
    main()
