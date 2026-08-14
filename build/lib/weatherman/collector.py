from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from . import __version__
from .db import (
    CollectionCoverage,
    CollectionRun,
    Forecast,
    ForecastSnapshot,
    MarketSnapshot,
    Observation,
    Session,
    TafReport,
    init_db,
    refresh_database_connections,
)
from .history import (
    DEFAULT_ARCHIVE_DIRECTORY,
    read_archive_live,
    validate_history_archive,
)
from .maintenance import (
    DATABASE_WARNING_BYTES,
    configured_sqlite_path,
)
from .service import (
    backfill_market_history,
    backfill_taf_revision,
    collect,
    collect_aviation_journal,
    collect_live_decision_checkpoints,
    collect_research_checkpoints,
)
from .settings import ROOT, trading_airports


COLLECTOR_INTERVAL_MINUTES = 10
LATEST_COVERAGE_REPORT = ROOT / "data" / "collection" / "coverage-latest.json"
STAGE1_RECOVERY_REPORT = (
    ROOT / "data" / "collection" / "recovery-2026-08-10-11.json"
)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _scheduled_at(started_at: datetime) -> datetime:
    configured = os.getenv("WEATHERMAN_SCHEDULED_AT", "").strip()
    if configured:
        parsed = datetime.fromisoformat(configured.replace("Z", "+00:00"))
        return _utc(parsed)
    minute = started_at.minute - started_at.minute % COLLECTOR_INTERVAL_MINUTES
    return started_at.replace(minute=minute, second=0, microsecond=0)


def _run_id() -> str:
    github_id = os.getenv("GITHUB_RUN_ID", "").strip()
    attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1").strip()
    return f"github-{github_id}-{attempt}" if github_id else f"local-{uuid.uuid4()}"


def _json(payload: object) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _start_run(
    run_id: str,
    *,
    scheduled_at: datetime,
    started_at: datetime,
    trigger: str,
    airport_codes: list[str],
) -> None:
    with Session() as session:
        # If a prior pending row is present in the database checked out by this
        # run, its Git commit necessarily reached main successfully.
        prior = list(
            session.scalars(
                select(CollectionRun).where(
                    CollectionRun.persistence_status == "pending_commit",
                    CollectionRun.ended_at.is_not(None),
                )
            )
        )
        for row in prior:
            row.persistence_status = "persisted"
            prior_coverage = list(
                session.scalars(
                    select(CollectionCoverage).where(
                        CollectionCoverage.run_id == row.run_id,
                        CollectionCoverage.status == "stored_pending_persistence",
                    )
                )
            )
            for coverage in prior_coverage:
                coverage.status = "stored_persisted"
        session.add(
            CollectionRun(
                run_id=run_id,
                scheduled_at=scheduled_at,
                started_at=started_at,
                collector_version=__version__,
                trigger=trigger,
                overall_status="running",
                scheduler_drift_seconds=max(
                    0.0, (started_at - scheduled_at).total_seconds()
                ),
                airports_json=_json(airport_codes),
                source_status_json="{}",
                rows_read_json="{}",
                rows_written_json="{}",
                source_age_json="{}",
                persistence_status="pending_commit",
            )
        )
        session.commit()


def _finish_run(
    run_id: str,
    *,
    status: str,
    results: dict[str, object],
    coverage: list[dict[str, object]],
    error_reason: str | None = None,
) -> None:
    ended_at = datetime.now(timezone.utc)
    with Session() as session:
        row = session.scalar(select(CollectionRun).where(CollectionRun.run_id == run_id))
        if row is None:
            return
        row.ended_at = ended_at
        row.overall_status = status
        row.error_reason = error_reason
        row.source_status_json = _json(
            {item["airport"] + "/" + item["data_type"]: item["status"] for item in coverage}
        )
        row.rows_read_json = _json(
            {item["airport"] + "/" + item["data_type"]: item["rows_read"] for item in coverage}
        )
        row.rows_written_json = _json(
            {
                **{
                    item["airport"] + "/" + item["data_type"]: item["rows_written"]
                    for item in coverage
                },
                "collector": results,
            }
        )
        row.source_age_json = _json(
            {
                item["airport"] + "/" + item["data_type"]: item["source_age_minutes"]
                for item in coverage
            }
        )
        for item in coverage:
            session.add(
                CollectionCoverage(
                    run_id=run_id,
                    airport=str(item["airport"]),
                    data_type=str(item["data_type"]),
                    status=str(item["status"]),
                    scheduled_at=row.scheduled_at,
                    latest_source_at=item.get("latest_source_at"),
                    rows_read=int(item.get("rows_read", 0)),
                    rows_written=int(item.get("rows_written", 0)),
                    source_age_minutes=item.get("source_age_minutes"),
                    reason=item.get("reason"),
                )
            )
        session.commit()


def _recover_madrid_taf_gap() -> dict[str, object]:
    target_issue = datetime(2026, 8, 10, 11, tzinfo=timezone.utc)
    with Session() as session:
        history = read_archive_live(
            TafReport,
            session.bind,
            filters={"airport": "LEMD", "issue_time": target_issue},
        )
    exact_revision = (
        not history.empty
        and "raw_taf" in history
        and history.raw_taf.astype(str).str.contains(
            r"\bLEMD\s+101100Z\b.*\bTX38/1016Z\b", regex=True
        ).any()
    )
    if exact_revision:
        return {"status": "already_present", "issue_time": target_issue.isoformat()}
    if datetime.now(timezone.utc) > target_issue + timedelta(days=15):
        return {
            "status": "outside_provider_retention",
            "issue_time": target_issue.isoformat(),
        }
    try:
        return backfill_taf_revision(
            ["LEMD"], target_issue + timedelta(minutes=30)
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "issue_time": target_issue.isoformat(),
            "reason": f"{type(exc).__name__}: {exc}",
        }


def run_collector(
    airport_codes: list[str] | None = None,
    *,
    now: datetime | None = None,
    trigger: str | None = None,
    force_models: bool = False,
    recover_known_gap: bool = True,
) -> dict[str, object]:
    """Run every scheduled write through one auditable Python entry point."""
    init_db()
    started_at = _utc(now or datetime.now(timezone.utc))
    scheduled_at = _scheduled_at(started_at)
    run_id = _run_id()
    catalog = trading_airports()
    requested = [code for code in (airport_codes or list(catalog)) if code in catalog]
    _start_run(
        run_id,
        scheduled_at=scheduled_at,
        started_at=started_at,
        trigger=trigger or os.getenv("GITHUB_EVENT_NAME", "manual"),
        airport_codes=requested,
    )
    coverage: list[dict[str, object]] = []
    results: dict[str, object] = {}
    try:
        aviation = collect_aviation_journal(requested, now=started_at)
        coverage.extend(aviation["coverage"])
        results["aviation"] = aviation["counts"]
        results["taf_gap_recovery"] = (
            _recover_madrid_taf_gap() if recover_known_gap else {"status": "skipped"}
        )
        results["checkpoints"] = collect_research_checkpoints(
            requested,
            window_minutes=35,
            catchup_hours=48,
            sync_universe=False,
            now=started_at,
        )
        if force_models:
            results["forced_models"] = collect(requested, days=3)
        results["live_decisions"] = collect_live_decision_checkpoints(
            requested,
            now=started_at,
            aviation_already_collected=True,
        )
        _finish_run(run_id, status="success", results=results, coverage=coverage)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        _finish_run(
            run_id,
            status="failed",
            results=results,
            coverage=coverage,
            error_reason=reason,
        )
        raise
    return {
        "run_id": run_id,
        "scheduled_at": scheduled_at.isoformat(),
        "started_at": started_at.isoformat(),
        "status": "success",
        **results,
    }


def recover_stage1_gaps(
    airport_codes: list[str] | None = None,
    *,
    now: datetime | None = None,
    report_path: Path = STAGE1_RECOVERY_REPORT,
) -> dict[str, object]:
    """Recover what is still causally reconstructable for 10/11 August 2026.

    The report deliberately distinguishes official/provider history from original
    live state.  It never relabels a later fetch as a contemporaneous snapshot.
    """
    started_at = _utc(now or datetime.now(timezone.utc))
    collector = run_collector(
        airport_codes,
        now=started_at,
        trigger="stage1-gap-recovery",
        force_models=True,
        recover_known_gap=True,
    )
    markets = backfill_market_history(2, airport_codes)
    report: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collector_version": __version__,
        "scope": "2026-08-10 through 2026-08-11 Stage-1 gaps",
        "collector": collector,
        "market_history": markets,
        "classification": {
            "metar": {
                "status": "provider_history_or_live",
                "detail": "Stored observations retain their observed time and actual fetch time.",
            },
            "taf": {
                "status": "official_revision_backfill",
                "detail": (
                    "The known LEMD 2026-08-10 11:00Z revision is requested exactly; "
                    "backfilled first-seen time prevents historical leakage."
                ),
            },
            "scheduled_checkpoints": {
                "status": "reconstructed_causal_where_possible",
                "detail": (
                    "Only inputs whose provider availability predates the checkpoint "
                    "are eligible; reconstruction is explicitly marked."
                ),
            },
            "market": {
                "status": "historical_samples_not_original_orderbook",
                "detail": "D-1/D0 historical samples are backfilled from provider history.",
            },
            "original_live_states": {
                "status": "not_recoverable",
                "detail": (
                    "Missed screen state, original order book and unrecorded intraday "
                    "snapshots are not recreated or presented as observed live history."
                ),
            },
        },
    }
    _atomic_json(report_path, report)
    return report


def coverage_audit(
    *,
    now: datetime | None = None,
    report_path: Path = LATEST_COVERAGE_REPORT,
    full_archive_validation: bool = True,
) -> dict[str, object]:
    """Explain recent collector gaps, stale sources and archive/DB health."""
    init_db()
    checked_at = _utc(now or datetime.now(timezone.utc))
    warnings: list[dict[str, object]] = []
    catalog = trading_airports()
    with Session() as session:
        runs = pd.read_sql(
            select(CollectionRun).where(
                CollectionRun.scheduled_at >= checked_at - timedelta(hours=24)
            ),
            session.bind,
        )
        if runs.empty:
            warnings.append(
                {
                    "severity": "error",
                    "type": "collector_missing",
                    "message": "No collector run is stored for the last 24 hours.",
                }
            )
        else:
            runs["scheduled_at"] = pd.to_datetime(runs.scheduled_at, utc=True)
            runs = runs.sort_values("scheduled_at")
            gaps = runs.scheduled_at.diff().dt.total_seconds().div(60).dropna()
            if not gaps.empty and float(gaps.max()) > 20:
                warnings.append(
                    {
                        "severity": "warning",
                        "type": "collector_historical_gap",
                        "active": False,
                        "message": (
                            "Historical 24-hour collector gap: "
                            f"{float(gaps.max()):.0f} minutes."
                        ),
                    }
                )
                recent_gap_indexes = runs.index[
                    runs.scheduled_at >= checked_at - timedelta(hours=1)
                ]
                recent_gaps = gaps[gaps.index.isin(recent_gap_indexes)]
                if not recent_gaps.empty and float(recent_gaps.max()) > 20:
                    warnings.append(
                        {
                            "severity": "error",
                            "type": "collector_gap",
                            "active": True,
                            "message": (
                                "Current collector cadence is not ten-minute complete; "
                                f"the largest recent gap is {float(recent_gaps.max()):.0f} minutes."
                            ),
                        }
                    )
            latest_run_age = (
                pd.Timestamp(checked_at) - runs.scheduled_at.max()
            ).total_seconds() / 60
            if latest_run_age > 20:
                warnings.append(
                    {
                        "severity": "error",
                        "type": "collector_missing_recent",
                        "active": True,
                        "message": (
                            "No collector run has been stored for "
                            f"{latest_run_age:.0f} minutes."
                        ),
                    }
                )
            failed = runs[runs.overall_status != "success"]
            for row in failed.itertuples():
                later_success = (
                    (runs.scheduled_at > row.scheduled_at)
                    & (runs.overall_status == "success")
                ).any()
                warnings.append(
                    {
                        "severity": "error",
                        "type": "collector_failed",
                        "active": not bool(later_success),
                        "message": f"Run {row.run_id} ended as {row.overall_status}: {row.error_reason}",
                    }
                )
            late = runs[runs.scheduler_drift_seconds > 15 * 60]
            for row in late.itertuples():
                warnings.append(
                    {
                        "severity": "warning",
                        "type": "collector_late",
                        "active": bool(
                            row.scheduled_at >= checked_at - timedelta(hours=1)
                        ),
                        "message": f"Run {row.run_id} started {row.scheduler_drift_seconds / 60:.0f} minutes late.",
                    }
                )

        for code, airport in catalog.items():
            def source_frame(model):
                if full_archive_validation:
                    return read_archive_live(
                        model,
                        session.bind,
                        filters={"airport": code},
                    )
                return pd.read_sql(
                    select(model).where(model.airport == code),
                    session.bind,
                )

            observations = source_frame(Observation)
            forecasts = source_frame(Forecast)
            tafs = source_frame(TafReport)
            markets = source_frame(MarketSnapshot)
            for data_type, frame, column, maximum_age in (
                ("METAR", observations, "observed_at", 90),
                ("forecast", forecasts, "fetched_at", 210),
                ("TAF", tafs, "fetched_at", 720),
                ("market", markets, "captured_at", 180),
            ):
                if frame.empty or column not in frame:
                    warnings.append(
                        {
                            "severity": "warning",
                            "type": "source_missing",
                            "airport": code,
                            "data_type": data_type,
                            "message": f"{code}: no {data_type} data is stored.",
                        }
                    )
                    continue
                latest = pd.to_datetime(frame[column], utc=True, errors="coerce").max()
                if pd.isna(latest):
                    continue
                age = (pd.Timestamp(checked_at) - latest).total_seconds() / 60
                local = checked_at.astimezone(ZoneInfo(airport["timezone"]))
                in_active_day = 5 <= local.hour <= 22
                if in_active_day and age > maximum_age:
                    warnings.append(
                        {
                            "severity": "warning",
                            "type": "source_stale",
                            "airport": code,
                            "data_type": data_type,
                            "age_minutes": round(age, 1),
                            "message": f"{code}: {data_type} is {age:.0f} minutes old.",
                        }
                    )

            snapshots = source_frame(ForecastSnapshot)
            local_today = checked_at.astimezone(ZoneInfo(airport["timezone"])).date()
            for target in (local_today, local_today + timedelta(days=1)):
                for label, day_offset, hour in (
                    ("D-1 @20", -1, 20),
                    ("D0 @06", 0, 6),
                    ("D0 @10", 0, 10),
                ):
                    cutoff = datetime.combine(
                        target + timedelta(days=day_offset),
                        datetime.min.time().replace(hour=hour),
                        ZoneInfo(airport["timezone"]),
                    ).astimezone(timezone.utc)
                    if checked_at < cutoff + timedelta(minutes=35):
                        continue
                    candidates = snapshots
                    if not candidates.empty:
                        candidates = candidates[
                            (pd.to_datetime(candidates.target_date).dt.date == target)
                            & (candidates.checkpoint_label == label)
                        ]
                    if candidates.empty:
                        warnings.append(
                            {
                                "severity": "error",
                                "type": "checkpoint_missing",
                                "airport": code,
                                "checkpoint": label,
                                "target_date": target.isoformat(),
                                "message": f"{code}: {label} is missing for {target}.",
                            }
                        )

    database_path = configured_sqlite_path()
    database_bytes = database_path.stat().st_size if database_path and database_path.exists() else 0
    if database_bytes >= DATABASE_WARNING_BYTES:
        warnings.append(
            {
                "severity": "error",
                "type": "database_growth",
                "database_bytes": database_bytes,
                "message": f"Active SQLite is {database_bytes / 1024 / 1024:.1f} MiB.",
            }
        )
    if full_archive_validation:
        try:
            manifest = validate_history_archive(DEFAULT_ARCHIVE_DIRECTORY)
            archive_status = "verified"
        except Exception as exc:
            manifest = {}
            archive_status = "failed"
            warnings.append(
                {
                    "severity": "error",
                    "type": "archive_verification_failed",
                    "message": f"Archive validation failed: {type(exc).__name__}: {exc}",
                }
            )
    else:
        manifest_path = DEFAULT_ARCHIVE_DIRECTORY / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        archive_status = "deferred_to_daily_verification"
    for warning in warnings:
        warning.setdefault("active", True)
    active_warning_count = sum(bool(item.get("active")) for item in warnings)
    report: dict[str, object] = {
        "checked_at": checked_at.isoformat(),
        "collector_version": __version__,
        "database_bytes": database_bytes,
        "archive_status": archive_status,
        "archive_partitions": int(manifest.get("partition_count", 0)),
        "archive_rows": int(manifest.get("total_rows", 0)),
        "warning_count": len(warnings),
        "active_warning_count": active_warning_count,
        "warnings": warnings,
    }
    _atomic_json(report_path, report)
    refresh_database_connections()
    return report
