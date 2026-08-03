from __future__ import annotations

import sqlite3

from weatherman.maintenance import REDUNDANT_HOURLY_INDEXES, maintain_sqlite_database


def test_maintenance_bounds_only_hourly_paths_and_drops_redundant_indexes(tmp_path) -> None:
    database = tmp_path / "weatherman.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE hourly_forecasts (
            id INTEGER PRIMARY KEY,
            airport TEXT NOT NULL,
            model TEXT NOT NULL,
            run_at TEXT NOT NULL,
            valid_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE TABLE forecast_snapshots (id INTEGER PRIMARY KEY, marker TEXT)")
    connection.execute("INSERT INTO forecast_snapshots (marker) VALUES ('keep me')")
    connection.executemany(
        "INSERT INTO hourly_forecasts (airport, model, run_at, valid_at) VALUES (?, ?, ?, ?)",
        [
            ("EDDM", "ecmwf", "2026-07-27 12:00:00", "2026-07-27 15:00:00"),
            ("EDDM", "ecmwf", "2026-07-28 12:00:00", "2026-07-28 15:00:00"),
            ("EDDM", "ecmwf", "2026-08-03 12:00:00", "2026-08-03 15:00:00"),
        ],
    )
    for index_name, column in zip(
        REDUNDANT_HOURLY_INDEXES,
        ("airport", "model", "run_at", "valid_at"),
        strict=True,
    ):
        connection.execute(f'CREATE INDEX "{index_name}" ON hourly_forecasts ({column})')
    connection.commit()
    connection.close()

    result = maintain_sqlite_database(database, hourly_retention_days=7)

    connection = sqlite3.connect(database)
    kept_runs = [
        row[0]
        for row in connection.execute(
            "SELECT run_at FROM hourly_forecasts ORDER BY run_at"
        ).fetchall()
    ]
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    marker = connection.execute("SELECT marker FROM forecast_snapshots").fetchone()[0]
    connection.close()

    assert kept_runs == ["2026-07-28 12:00:00", "2026-08-03 12:00:00"]
    assert marker == "keep me"
    assert not indexes.intersection(REDUNDANT_HOURLY_INDEXES)
    assert result["hourly_forecasts_pruned"] == 1
    assert result["indexes_dropped"] == 4
    assert result["vacuumed"] is True


def test_maintenance_skips_missing_database(tmp_path) -> None:
    result = maintain_sqlite_database(tmp_path / "missing.db")

    assert result["status"] == "skipped_missing_database"
    assert result["database_bytes"] == 0
