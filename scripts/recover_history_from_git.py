from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

from weatherman.history import (
    ARCHIVE_SPECS,
    archive_table_rows,
    validate_history_archive,
)


def _source(value: str) -> tuple[str, date]:
    try:
        commit, day = value.split(":", 1)
        return commit, date.fromisoformat(day)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected COMMIT:YYYY-MM-DD") from exc


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def recover_partition(
    *,
    commit: str,
    day: date,
    database_path: str,
    archive_directory: Path,
) -> dict[str, object]:
    """Recover one UTC partition from a historical, committed SQLite snapshot."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as handle:
        payload = subprocess.run(
            ["git", "show", f"{commit}:{database_path}"],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        handle.write(payload)
        handle.flush()
        connection = sqlite3.connect(handle.name)
        connection.row_factory = sqlite3.Row
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"{commit} SQLite quick_check failed: {integrity}")
            available_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            start = day.isoformat()
            end = (day + timedelta(days=1)).isoformat()
            results: dict[str, object] = {}
            for table, spec in ARCHIVE_SPECS.items():
                if table not in available_tables:
                    continue
                columns = [
                    str(row[1])
                    for row in connection.execute(f"PRAGMA table_info({_quoted(table)})")
                ]
                rows = [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT * FROM {_quoted(table)} "
                        f"WHERE {_quoted(spec.event_time)} >= ? "
                        f"AND {_quoted(spec.event_time)} < ?",
                        (start, end),
                    )
                ]
                if not rows:
                    continue
                results[table] = archive_table_rows(
                    rows,
                    spec=spec,
                    columns=columns,
                    directory=archive_directory,
                )
        finally:
            connection.close()
    return {
        "commit": commit,
        "utc_date": day.isoformat(),
        "tables": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover missing immutable archive partitions from Git SQLite history."
    )
    parser.add_argument("--source", action="append", required=True, type=_source)
    parser.add_argument("--database-path", default="data/weatherman.db")
    parser.add_argument(
        "--archive-directory", type=Path, default=Path("data/history_archive")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/research/history-gap-recovery-v10710.json"),
    )
    args = parser.parse_args()
    recoveries = [
        recover_partition(
            commit=commit,
            day=day,
            database_path=args.database_path,
            archive_directory=args.archive_directory,
        )
        for commit, day in args.source
    ]
    manifest = validate_history_archive(args.archive_directory)
    report = {
        "status": "recovered-and-verified",
        "method": "exact UTC partitions from committed SQLite snapshots",
        "sources": recoveries,
        "archive_partition_count": int(manifest.get("partition_count", 0)),
        "archive_total_rows": int(manifest.get("total_rows", 0)),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
