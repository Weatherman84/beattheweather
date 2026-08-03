from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .settings import ROOT, settings


REDUNDANT_HOURLY_INDEXES = (
    "ix_hourly_forecasts_airport",
    "ix_hourly_forecasts_model",
    "ix_hourly_forecasts_run_at",
    "ix_hourly_forecasts_valid_at",
)


def configured_sqlite_path() -> Path | None:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    path = Path(settings.database_url.removeprefix(prefix))
    return path if path.is_absolute() else ROOT / path


def maintain_sqlite_database(
    database_path: Path | None = None,
    *,
    hourly_retention_days: int = 7,
) -> dict[str, int | bool | str]:
    """Bound transient hourly history while preserving research snapshots.

    Daily forecasts, actuals, observations, market history, signals and every
    forecast/challenger snapshot are intentionally untouched. Hourly model
    paths are operational inputs and only the seven latest UTC run dates are
    needed by the live application.
    """
    if hourly_retention_days < 1:
        raise ValueError("hourly_retention_days must be at least 1")

    path = database_path or configured_sqlite_path()
    if path is None:
        return {
            "status": "skipped_non_sqlite",
            "hourly_forecasts_pruned": 0,
            "indexes_dropped": 0,
            "vacuumed": False,
            "database_bytes": 0,
        }
    path = Path(path)
    if not path.exists():
        return {
            "status": "skipped_missing_database",
            "hourly_forecasts_pruned": 0,
            "indexes_dropped": 0,
            "vacuumed": False,
            "database_bytes": 0,
        }

    connection = sqlite3.connect(path, timeout=60)
    pruned = 0
    dropped = 0
    cutoff = ""
    try:
        connection.execute("PRAGMA busy_timeout = 60000")
        has_hourly = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'hourly_forecasts'"
        ).fetchone()
        if has_hourly:
            latest_run = connection.execute(
                "SELECT MAX(run_at) FROM hourly_forecasts"
            ).fetchone()[0]
            if latest_run:
                latest_day = datetime.fromisoformat(str(latest_run).replace("Z", "+00:00")).date()
                first_kept_day = latest_day - timedelta(days=hourly_retention_days - 1)
                cutoff = f"{first_kept_day.isoformat()} 00:00:00"
                cursor = connection.execute(
                    "DELETE FROM hourly_forecasts WHERE run_at < ?",
                    (cutoff,),
                )
                pruned = max(int(cursor.rowcount), 0)

        existing_indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        for index_name in REDUNDANT_HOURLY_INDEXES:
            if index_name in existing_indexes:
                connection.execute(f'DROP INDEX "{index_name}"')
                dropped += 1
        connection.commit()

        should_vacuum = bool(pruned or dropped)
        if should_vacuum:
            connection.execute("VACUUM")
        connection.execute("PRAGMA optimize")
    finally:
        connection.close()

    return {
        "status": "maintained",
        "hourly_forecasts_pruned": pruned,
        "indexes_dropped": dropped,
        "hourly_cutoff": cutoff,
        "vacuumed": should_vacuum,
        "database_bytes": path.stat().st_size,
    }
