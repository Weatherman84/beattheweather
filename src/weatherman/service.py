from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from .analytics import detect_market_model_conflict, market_edges
from .db import (
    DailyActual,
    Forecast,
    ForecastSnapshot,
    HourlyForecast,
    MarketSnapshot,
    Observation,
    Session,
    SignalSnapshot,
    TafReport,
    init_db,
)
from .nowcast import build_live_nowcast
from .providers import (
    historical_actuals,
    meteoblue_forecast,
    open_meteo_forecast,
    open_meteo_hourly,
    polymarket_prices,
    previous_run_d1,
    recent_metars,
    recent_tafs,
)
from .settings import airports


def _upsert(session, model, keys: dict, values: dict) -> None:
    row = session.scalar(select(model).filter_by(**keys))
    if row is None:
        session.add(model(**keys, **values))
    else:
        for key, value in values.items():
            setattr(row, key, value)


def _upsert_batch(
    session,
    model,
    rows: Iterable[dict],
    keys: Callable[[dict], dict],
    values: Callable[[dict], dict],
    label: str,
) -> int:
    """Store one source atomically so a bad row cannot poison the whole collection."""
    items = list(rows)
    if not items:
        return 0
    try:
        with session.begin_nested():
            for item in items:
                _upsert(session, model, keys(item), values(item))
            session.flush()
    except Exception as exc:
        print(f"WARN {label} storage rolled back: {type(exc).__name__}: {exc}")
        return 0
    return len(items)


def _signal_timing(captured_at: datetime, target: date, timezone_name: str) -> str:
    local = captured_at.astimezone(ZoneInfo(timezone_name))
    if local.date() < target:
        return "D-1 or earlier"
    if local.date() > target:
        return "After target day"
    return "D0 morning" if local.hour < 12 else "D0 live"


def _build_nowcast_from_session(
    session,
    code: str,
    airport: dict,
    target: date,
    captured_at: datetime,
    market_rows: list[dict],
):
    connection = session.connection()
    forecasts = pd.read_sql(select(Forecast).where(Forecast.airport == code), connection)
    actuals = pd.read_sql(select(DailyActual).where(DailyActual.airport == code), connection)
    observations = pd.read_sql(
        select(Observation).where(Observation.airport == code), connection
    )
    hourly = pd.read_sql(
        select(HourlyForecast).where(HourlyForecast.airport == code), connection
    )
    tafs = pd.read_sql(select(TafReport).where(TafReport.airport == code), connection)
    return build_live_nowcast(
        forecasts=forecasts,
        actuals=actuals,
        observations=observations,
        hourly=hourly,
        markets=pd.DataFrame(market_rows),
        tafs=tafs,
        timezone_name=airport["timezone"],
        target=target,
        as_of=captured_at,
        wind_profile=airport.get("heat_wind_profile"),
        routine_metar_minutes=airport.get("metar_minutes"),
    )


def _record_forecast_snapshot(
    session,
    code: str,
    airport: dict,
    target: date,
    captured_at: datetime,
    nowcast,
) -> int:
    """Persist one comparable observation of every forecast transformation."""
    if nowcast is None:
        return 0
    local_capture = captured_at.astimezone(ZoneInfo(airport["timezone"]))
    metar_conditioned_available = (
        target == local_capture.date() and nowcast.observed_max is not None
    )
    guidance = nowcast.taf_guidance
    taf_conflict = bool(
        guidance is not None
        and (
            guidance.agreement.startswith("Mild conflict")
            or guidance.agreement.startswith("Contradicts model")
        )
    )
    row = {
        "airport": code,
        "target_date": target,
        "captured_at": captured_at,
        "timing": _signal_timing(captured_at, target, airport["timezone"]),
        "raw_model_mean_c": nowcast.raw_model_mean,
        "bias_corrected_c": nowcast.corrected.mean,
        "metar_conditioned_c": (
            nowcast.metar_conditioned_mean if metar_conditioned_available else None
        ),
        "final_forecast_c": nowcast.final_forecast_mean,
        "raw_spread_c": nowcast.raw_model_spread,
        "bias_corrected_spread_c": nowcast.corrected.spread,
        "metar_conditioned_spread_c": (
            nowcast.metar_conditioned_spread if metar_conditioned_available else None
        ),
        "final_spread_c": nowcast.final_forecast_spread,
        "observed_max_c": nowcast.observed_max,
        "latest_metar_at": nowcast.latest_observation_at,
        "expected_peak_at": nowcast.expected_peak_at,
        "hours_to_peak": nowcast.hours_to_peak,
        "day_phase": nowcast.day_status.phase,
        "model_count": len(nowcast.current),
        "taf_adjustment_c": nowcast.taf_adjustment_c,
        "taf_conflict": taf_conflict,
    }
    return _upsert_batch(
        session,
        ForecastSnapshot,
        [row],
        lambda item: {
            "airport": item["airport"],
            "target_date": item["target_date"],
            "captured_at": item["captured_at"],
        },
        lambda item: {
            key: value
            for key, value in item.items()
            if key not in {"airport", "target_date", "captured_at"}
        },
        f"{code}/forecast ladder/{target}",
    )


def _record_signal_snapshots(
    session,
    code: str,
    airport: dict,
    market_rows: list[dict],
    nowcast=None,
) -> int:
    """Journal the exact model-versus-market view created by this collection."""
    if not market_rows or all(bool(row.get("closed")) for row in market_rows):
        return 0
    captured_at = max(row["captured_at"] for row in market_rows)
    target = market_rows[0]["target_date"]
    market_frame = pd.DataFrame(market_rows)
    if nowcast is None:
        nowcast = _build_nowcast_from_session(
            session, code, airport, target, captured_at, market_rows
        )
    if nowcast is None:
        return 0
    comparison = market_edges(nowcast.probabilities, market_frame)
    conflict = detect_market_model_conflict(nowcast.probabilities, market_frame)
    if nowcast.day_status.is_locked:
        comparison["signal"] = "Day complete"
    elif nowcast.metar_pending:
        comparison["signal"] = "METAR pending"
    elif conflict.is_conflict:
        comparison["signal"] = "Market-model conflict"
    timing = _signal_timing(captured_at, target, airport["timezone"])
    rows = []
    for row in comparison.itertuples():
        rows.append(
            {
                "market_id": str(row.market_id),
                "captured_at": captured_at,
                "airport": code,
                "target_date": target,
                "event_slug": str(row.event_slug),
                "bucket_label": str(row.bucket_label),
                "timing": timing,
                "model_probability": float(row.model_probability),
                "market_probability": float(row.yes_price),
                "buy_price": float(row.buy_price) if pd.notna(row.buy_price) else None,
                "edge": float(row.edge) if pd.notna(row.edge) else None,
                "signal": str(row.signal),
                "day_phase": nowcast.day_status.phase,
                "model_count": len(nowcast.current),
            }
        )
    return _upsert_batch(
        session,
        SignalSnapshot,
        rows,
        lambda item: {
            "market_id": item["market_id"],
            "captured_at": item["captured_at"],
        },
        lambda item: {
            key: value
            for key, value in item.items()
            if key not in {"market_id", "captured_at"}
        },
        f"{code}/signal journal/{target}",
    )


def collect(airport_codes: list[str] | None = None, days: int = 3) -> dict[str, int]:
    init_db()
    counts = {
        "forecasts": 0,
        "hourly_forecasts": 0,
        "observations": 0,
        "taf_reports": 0,
        "market_prices": 0,
        "signals": 0,
        "forecast_snapshots": 0,
        "actuals": 0,
    }
    catalog = airports()
    selected_codes = airport_codes or list(catalog)
    try:
        fetched_tafs = recent_tafs(selected_codes)
    except Exception as exc:
        print(f"WARN TAF: {exc}")
        fetched_tafs = []
    with Session() as session:
        for code in selected_codes:
            airport = catalog[code]
            batches = []
            for model in airport["models"]:
                try:
                    batches.extend(open_meteo_forecast(airport, model, days))
                except Exception as exc:
                    print(f"WARN {code}/{model}: {exc}")
                try:
                    hourly_rows = open_meteo_hourly(airport, model, days)
                except Exception as exc:
                    print(f"WARN {code}/{model} hourly: {exc}")
                else:
                    counts["hourly_forecasts"] += _upsert_batch(
                        session,
                        HourlyForecast,
                        hourly_rows,
                        lambda item: {
                            "airport": code,
                            "model": item["model"],
                            "run_at": item["run_at"],
                            "valid_at": item["valid_at"],
                        },
                        lambda item: {
                            "temp_c": item["temp_c"],
                            "dewpoint_c": item["dewpoint_c"],
                            "cloud_cover": item["cloud_cover"],
                            "wind_kph": item["wind_kph"],
                            "wind_direction": item["wind_direction"],
                            "radiation_wm2": item["radiation_wm2"],
                            "temp_850hpa_c": item["temp_850hpa_c"],
                        },
                        f"{code}/{model} hourly",
                    )
            try:
                batches.extend(meteoblue_forecast(airport))
            except Exception as exc:
                print(f"WARN {code}/meteoblue: {exc}")
            counts["forecasts"] += _upsert_batch(
                session,
                Forecast,
                batches,
                lambda item: {
                    "airport": code,
                    "model": item["model"],
                    "run_at": item["run_at"],
                    "target_date": item["target_date"],
                },
                lambda item: {
                    "max_temp_c": item["max_temp_c"],
                    "source": item["source"],
                    "horizon": item["horizon"],
                },
                f"{code} daily forecasts",
            )
            try:
                metar_rows = recent_metars(code)
            except Exception as exc:
                print(f"WARN {code}/METAR: {exc}")
            else:
                counts["observations"] += _upsert_batch(
                    session,
                    Observation,
                    metar_rows,
                    lambda item: {"airport": code, "observed_at": item["observed_at"]},
                    lambda item: {
                        key: value for key, value in item.items() if key != "observed_at"
                    },
                    f"{code}/METAR",
                )
            airport_tafs = [row for row in fetched_tafs if row["airport"] == code]
            counts["taf_reports"] += _upsert_batch(
                session,
                TafReport,
                airport_tafs,
                lambda item: {
                    "airport": code,
                    "issue_time": item["issue_time"],
                    "raw_taf": item["raw_taf"],
                },
                lambda item: {
                    key: value
                    for key, value in item.items()
                    if key not in {"airport", "issue_time", "raw_taf", "collected_at"}
                },
                f"{code}/TAF",
            )
            actual_end = date.today() - timedelta(days=6)
            actual_start = actual_end - timedelta(days=13)
            try:
                actual_rows = historical_actuals(airport, actual_start, actual_end)
            except Exception as exc:
                print(f"WARN {code}/recent actuals: {exc}")
            else:
                counts["actuals"] += _upsert_batch(
                    session,
                    DailyActual,
                    actual_rows,
                    lambda item: {"airport": code, "target_date": item["target_date"]},
                    lambda item: {
                        "max_temp_c": item["max_temp_c"],
                        "source": "open-meteo-archive",
                    },
                    f"{code}/recent actuals",
                )
            local_today = datetime.now(ZoneInfo(airport["timezone"])).date()
            for offset in range(-2, days):
                market_target = local_today + timedelta(days=offset)
                market_rows: list[dict] = []
                try:
                    market_rows = polymarket_prices(airport, market_target)
                except Exception as exc:
                    print(f"WARN {code}/Polymarket/{market_target}: {exc}")
                else:
                    counts["market_prices"] += _upsert_batch(
                        session,
                        MarketSnapshot,
                        market_rows,
                        lambda item: {
                            "market_id": item["market_id"],
                            "captured_at": item["captured_at"],
                        },
                        lambda item: {
                            "airport": code,
                            **{
                                key: value
                                for key, value in item.items()
                                if key not in {"market_id", "captured_at"}
                            },
                        },
                        f"{code}/Polymarket/{market_target}",
                    )
                if offset >= 0:
                    captured_at = (
                        max(row["captured_at"] for row in market_rows)
                        if market_rows
                        else datetime.now(timezone.utc)
                    )
                    try:
                        nowcast = _build_nowcast_from_session(
                            session,
                            code,
                            airport,
                            market_target,
                            captured_at,
                            market_rows,
                        )
                        counts["forecast_snapshots"] += _record_forecast_snapshot(
                            session,
                            code,
                            airport,
                            market_target,
                            captured_at,
                            nowcast,
                        )
                        if not market_rows:
                            continue
                        counts["signals"] += _record_signal_snapshots(
                            session, code, airport, market_rows, nowcast=nowcast
                        )
                    except Exception as exc:
                        print(f"WARN {code}/forecast journal/{market_target}: {exc}")
        session.commit()
    return counts


def collect_live_aviation(
    airport_code: str,
    *,
    include_taf: bool = False,
) -> dict[str, object]:
    """Lightweight dashboard poller: METAR every minute, TAF on a slower cadence."""
    init_db()
    catalog = airports()
    if airport_code not in catalog:
        raise KeyError(f"Unknown airport: {airport_code}")
    metar_rows = recent_metars(airport_code, attempts=1, timeout=5)
    taf_rows = (
        recent_tafs([airport_code], attempts=1, timeout=5) if include_taf else []
    )
    counts: dict[str, object] = {
        "observations": 0,
        "taf_reports": 0,
        "latest_metar": None,
        "latest_taf": None,
    }
    with Session() as session:
        counts["observations"] = _upsert_batch(
            session,
            Observation,
            metar_rows,
            lambda item: {"airport": airport_code, "observed_at": item["observed_at"]},
            lambda item: {
                key: value for key, value in item.items() if key != "observed_at"
            },
            f"{airport_code}/live METAR",
        )
        if taf_rows:
            counts["taf_reports"] = _upsert_batch(
                session,
                TafReport,
                taf_rows,
                lambda item: {
                    "airport": airport_code,
                    "issue_time": item["issue_time"],
                    "raw_taf": item["raw_taf"],
                },
                lambda item: {
                    key: value
                    for key, value in item.items()
                    if key not in {"airport", "issue_time", "raw_taf", "collected_at"}
                },
                f"{airport_code}/live TAF",
            )
        session.commit()
    if metar_rows:
        counts["latest_metar"] = max(row["observed_at"] for row in metar_rows)
    if taf_rows:
        counts["latest_taf"] = max(row["issue_time"] for row in taf_rows)
    return counts


def backfill(days: int = 365, airport_codes: list[str] | None = None) -> dict[str, int]:
    init_db()
    # Reanalysis products can arrive several days late. A six-day safety margin
    # prevents a whole first-time backfill from failing on incomplete recent data.
    end = date.today() - timedelta(days=6)
    start = end - timedelta(days=days - 1)
    counts = {"forecasts": 0, "actuals": 0}
    catalog = airports()
    with Session() as session:
        for code in airport_codes or list(catalog):
            airport = catalog[code]
            try:
                actual_rows = historical_actuals(airport, start, end)
                airport_actuals = _upsert_batch(
                    session,
                    DailyActual,
                    actual_rows,
                    lambda item: {"airport": code, "target_date": item["target_date"]},
                    lambda item: {
                        "max_temp_c": item["max_temp_c"],
                        "source": "open-meteo-archive",
                    },
                    f"{code}/historical actuals",
                )
                counts["actuals"] += airport_actuals
                print(f"OK {code}/actuals: {airport_actuals} days")
            except Exception as exc:
                print(f"WARN {code}/historical actuals: {exc}")
            for model in airport["models"]:
                try:
                    forecast_rows = previous_run_d1(airport, model, start, end)
                    model_rows = _upsert_batch(
                        session,
                        Forecast,
                        forecast_rows,
                        lambda item: {
                            "airport": code,
                            "model": model,
                            "run_at": item["run_at"],
                            "target_date": item["target_date"],
                        },
                        lambda item: {
                            "max_temp_c": item["max_temp_c"],
                            "source": item["source"],
                            "horizon": item["horizon"],
                        },
                        f"{code}/{model} backfill",
                    )
                    counts["forecasts"] += model_rows
                    print(f"OK {code}/{model}: {model_rows} days")
                except Exception as exc:
                    print(f"WARN {code}/{model} backfill: {exc}")
                # Keep the free data endpoint below burst-rate limits.
                time.sleep(1)
        session.commit()
    return counts
