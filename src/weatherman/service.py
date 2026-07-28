from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from .analytics import detect_market_model_conflict, market_edges
from .catalog import market_city_index, research_airports, trading_airports
from .db import (
    AirportMarketUniverse,
    DailyActual,
    Forecast,
    ForecastSnapshot,
    HourlyForecast,
    MarketSnapshot,
    Observation,
    Session,
    SignalSnapshot,
    StrategySnapshot,
    TafReport,
    init_db,
)
from .nowcast import build_live_nowcast
from .providers import (
    discover_polymarket_temperature_events,
    historical_actuals,
    meteoblue_forecast,
    open_meteo_forecast,
    open_meteo_hourly,
    polymarket_prices,
    polymarket_historical_prices,
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


def sync_airport_universe(*, include_closed: bool = False) -> dict[str, int]:
    """Persist every discovered market city, including cities without a station map."""
    init_db()
    events = discover_polymarket_temperature_events(include_closed=include_closed)
    city_index = market_city_index()
    now = datetime.now(timezone.utc)
    mapped = 0
    unknown = 0
    with Session() as session:
        if events and not include_closed:
            for existing in session.scalars(
                select(AirportMarketUniverse).where(AirportMarketUniverse.active.is_(True))
            ):
                existing.active = False
        for event in events:
            match = city_index.get(event["market_city"])
            code = match[0] if match else None
            details = match[1] if match else {}
            status = (
                details.get("station_match", "candidate station")
                if match
                else "station mapping required"
            )
            current = session.scalar(
                select(AirportMarketUniverse).where(
                    AirportMarketUniverse.market_city == event["market_city"]
                )
            )
            values = {
                "display_name": event["display_name"],
                "airport": code,
                "mapping_status": status,
                "market_unit": event.get("market_unit"),
                "resolution_source": event.get("resolution_source"),
                "last_seen_at": now,
                "latest_event_slug": event["event_slug"],
                "latest_target_date": event["target_date"],
                "active": bool(event.get("active", True)),
            }
            if current is None:
                session.add(
                    AirportMarketUniverse(
                        market_city=event["market_city"],
                        first_seen_at=now,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(current, key, value)
            mapped += int(code is not None)
            unknown += int(code is None)
        session.commit()
    return {"cities": len(events), "mapped": mapped, "unmapped": unknown}


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
    observations = pd.read_sql(select(Observation).where(Observation.airport == code), connection)
    hourly = pd.read_sql(select(HourlyForecast).where(HourlyForecast.airport == code), connection)
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
        critical_window_local=airport.get("critical_window_local"),
        post_convective_profile=airport.get("post_convective_uncertainty"),
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
        "weighted_raw_c": nowcast.weighted_raw_mean,
        "bias_corrected_equal_c": nowcast.bias_corrected_equal_mean,
        "bias_corrected_c": nowcast.corrected.mean,
        "metar_conditioned_c": (
            nowcast.metar_conditioned_mean if metar_conditioned_available else None
        ),
        "final_forecast_c": nowcast.final_forecast_mean,
        "raw_spread_c": nowcast.raw_model_spread,
        "weighted_raw_spread_c": nowcast.weighted_raw_spread,
        "bias_corrected_equal_spread_c": nowcast.bias_corrected_equal_spread,
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
        "temp_anchor_adjustment_c": nowcast.adjustment_contributions.get("temperature_anchor", 0.0),
        "dryness_adjustment_c": nowcast.adjustment_contributions.get("dryness", 0.0),
        "dewpoint_trend_adjustment_c": nowcast.adjustment_contributions.get("dewpoint_trend", 0.0),
        "cloud_adjustment_c": nowcast.adjustment_contributions.get("cloud", 0.0),
        "heating_rate_adjustment_c": nowcast.adjustment_contributions.get("heating_rate", 0.0),
        "recent_error_adjustment_c": nowcast.adjustment_contributions.get(
            "recent_station_error", 0.0
        ),
        "radiation_adjustment_c": nowcast.adjustment_contributions.get("radiation", 0.0),
        "wind_adjustment_c": nowcast.adjustment_contributions.get("wind", 0.0),
        "run_trend_adjustment_c": nowcast.adjustment_contributions.get("run_trend", 0.0),
        "late_dry_mixing_adjustment_c": nowcast.adjustment_contributions.get(
            "late_dry_mixing", 0.0
        ),
        "failed_convection_adjustment_c": nowcast.adjustment_contributions.get(
            "failed_convection", 0.0
        ),
        "post_convective_active": bool(
            nowcast.live_features.get("post_convective_uncertainty_active", 0)
        ),
        "post_convective_reports": int(
            nowcast.live_features.get("post_convective_reports_48h", 0) or 0
        ),
        "post_convective_spread_multiplier": float(
            nowcast.live_features.get("post_convective_spread_multiplier", 1.0)
            or 1.0
        ),
        "model_ceiling_reached_early": bool(
            nowcast.live_features.get("model_ceiling_reached_early", 0)
        ),
        "live_adjustment_c": nowcast.adjustment_contributions.get("total", 0.0),
        "features_json": json.dumps(nowcast.live_features, separators=(",", ":")),
        "peak_lock_json": json.dumps(
            {
                "phase": nowcast.day_status.phase,
                "label": nowcast.day_status.label,
                "explanation": nowcast.day_status.explanation,
                "remaining_model_rise_c": nowcast.remaining_rise_c,
                "future_radiation_max_wm2": nowcast.future_radiation_max,
                "observed_max_c": nowcast.observed_max,
            },
            separators=(",", ":"),
        ),
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
            key: value for key, value in item.items() if key not in {"market_id", "captured_at"}
        },
        f"{code}/signal journal/{target}",
    )


def _record_strategy_snapshots(
    session,
    code: str,
    airport: dict,
    market_rows: list[dict],
    nowcast,
) -> int:
    """Record one mode-bucket benchmark entry for every forecast stage."""
    if nowcast is None or not market_rows or all(bool(row.get("closed")) for row in market_rows):
        return 0
    captured_at = max(row["captured_at"] for row in market_rows)
    target = market_rows[0]["target_date"]
    timing = _signal_timing(captured_at, target, airport["timezone"])
    local_capture = captured_at.astimezone(ZoneInfo(airport["timezone"]))
    rows = []
    for strategy, probabilities in nowcast.stage_probabilities.items():
        if strategy == "METAR conditioned" and (
            target != local_capture.date() or nowcast.observed_max is None
        ):
            continue
        model_bucket = max(probabilities, key=probabilities.get)
        matches = [
            market
            for market in market_rows
            if (market.get("bucket_low_c") is None or model_bucket >= float(market["bucket_low_c"]))
            and (
                market.get("bucket_high_c") is None
                or model_bucket <= float(market["bucket_high_c"])
            )
        ]
        if not matches:
            continue
        market = min(
            matches,
            key=lambda item: (
                float("inf")
                if item.get("bucket_low_c") is None or item.get("bucket_high_c") is None
                else float(item["bucket_high_c"]) - float(item["bucket_low_c"])
            ),
        )
        buy_price = (
            float(market["best_ask"])
            if market.get("best_ask") is not None
            else float(market["yes_price"])
        )
        rows.append(
            {
                "airport": code,
                "target_date": target,
                "captured_at": captured_at,
                "timing": timing,
                "strategy": strategy,
                "market_id": str(market["market_id"]),
                "bucket_label": str(market["bucket_label"]),
                "model_bucket_c": int(model_bucket),
                "model_probability": float(probabilities[model_bucket]),
                "market_probability": float(market["yes_price"]),
                "buy_price": buy_price,
                "price_basis": (
                    "live best ask"
                    if market.get("best_ask") is not None
                    else "displayed market price"
                ),
                "day_phase": nowcast.day_status.phase,
            }
        )
    return _upsert_batch(
        session,
        StrategySnapshot,
        rows,
        lambda item: {
            "airport": item["airport"],
            "target_date": item["target_date"],
            "captured_at": item["captured_at"],
            "timing": item["timing"],
            "strategy": item["strategy"],
        },
        lambda item: {
            key: value
            for key, value in item.items()
            if key not in {"airport", "target_date", "captured_at", "timing", "strategy"}
        },
        f"{code}/strategy journal/{target}",
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
        "strategy_snapshots": 0,
        "forecast_snapshots": 0,
        "actuals": 0,
    }
    catalog = airports()
    selected_codes = airport_codes or list(catalog)
    if airport_codes is None:
        selected_codes = list(trading_airports())
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
                    "model_run_at": item.get("model_run_at"),
                    "available_at": item.get("available_at"),
                    "fetched_at": item.get("fetched_at", item["run_at"]),
                    "provenance_status": item.get("provenance_status"),
                },
                f"{code} daily forecasts",
            )
            try:
                metar_rows = recent_metars(code, hours=48)
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
                        counts["strategy_snapshots"] += _record_strategy_snapshots(
                            session, code, airport, market_rows, nowcast
                        )
                    except Exception as exc:
                        print(f"WARN {code}/forecast journal/{market_target}: {exc}")
        session.commit()
    return counts


def collect_research_checkpoints(
    airport_codes: list[str] | None = None,
    *,
    now: datetime | None = None,
    window_minutes: int = 30,
) -> dict[str, int]:
    """Collect lightweight model snapshots just before 20:00 D-1 and 10:00 D0.

    The workflow may run every 30 minutes, but only airports whose exact local
    checkpoint is imminent are fetched. Full METAR/TAF/Meteoblue collection remains
    limited to the Trading Desk airport tier.
    """
    init_db()
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    counts = {
        "universe_cities": 0,
        "mapped_cities": 0,
        "unmapped_cities": 0,
        "airports_due": 0,
        "forecasts": 0,
        "forecast_snapshots": 0,
        "actuals": 0,
    }
    try:
        universe_counts = sync_airport_universe()
    except Exception as exc:
        print(f"WARN Polymarket airport-universe sync: {exc}")
    else:
        counts["universe_cities"] = universe_counts["cities"]
        counts["mapped_cities"] = universe_counts["mapped"]
        counts["unmapped_cities"] = universe_counts["unmapped"]

    catalog = research_airports()
    with Session() as session:
        universe_rows = list(
            session.scalars(
                select(AirportMarketUniverse).where(
                    AirportMarketUniverse.active.is_(True),
                    AirportMarketUniverse.airport.is_not(None),
                )
            )
        )
        targets_by_airport: dict[str, set[date]] = {}
        for row in universe_rows:
            if row.airport and row.latest_target_date:
                targets_by_airport.setdefault(row.airport, set()).add(row.latest_target_date)
        selected_codes = airport_codes or sorted(targets_by_airport)
        for code in selected_codes:
            if code not in catalog:
                continue
            airport = catalog[code]
            zone = ZoneInfo(airport["timezone"])
            local_now = current_time.astimezone(zone)
            targets = targets_by_airport.get(code)
            if not targets and airport_codes:
                targets = {local_now.date(), local_now.date() + timedelta(days=1)}
            due: list[tuple[date, datetime]] = []
            for target in targets or set():
                checkpoints = (
                    datetime(
                        target.year,
                        target.month,
                        target.day,
                        10,
                        tzinfo=zone,
                    ),
                    datetime(
                        target.year,
                        target.month,
                        target.day,
                        20,
                        tzinfo=zone,
                    )
                    - timedelta(days=1),
                )
                for cutoff in checkpoints:
                    seconds_to_cutoff = (cutoff - local_now).total_seconds()
                    if 0 <= seconds_to_cutoff <= window_minutes * 60:
                        cutoff_utc = cutoff.astimezone(timezone.utc)
                        existing = session.scalar(
                            select(ForecastSnapshot.id).where(
                                ForecastSnapshot.airport == code,
                                ForecastSnapshot.target_date == target,
                                ForecastSnapshot.captured_at <= cutoff_utc,
                                ForecastSnapshot.captured_at
                                >= cutoff_utc - timedelta(minutes=window_minutes),
                            )
                        )
                        if existing is None:
                            due.append((target, cutoff_utc))
            if not due:
                continue
            counts["airports_due"] += 1
            batches: list[dict] = []
            models = airport.get(
                "research_models",
                ["ecmwf_ifs025", "gfs_global", "icon_global"],
            )
            for model in models:
                try:
                    batches.extend(open_meteo_forecast(airport, model, days=3))
                except Exception as exc:
                    print(f"WARN {code}/{model} research checkpoint: {exc}")
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
                    "model_run_at": item.get("model_run_at"),
                    "available_at": item.get("available_at"),
                    "fetched_at": item.get("fetched_at", item["run_at"]),
                    "provenance_status": item.get("provenance_status"),
                },
                f"{code}/research checkpoint forecasts",
            )
            try:
                actual_end = date.today() - timedelta(days=6)
                actual_rows = historical_actuals(
                    airport, actual_end - timedelta(days=13), actual_end
                )
            except Exception as exc:
                print(f"WARN {code}/research actuals: {exc}")
            else:
                counts["actuals"] += _upsert_batch(
                    session,
                    DailyActual,
                    actual_rows,
                    lambda item: {
                        "airport": code,
                        "target_date": item["target_date"],
                    },
                    lambda item: {
                        "max_temp_c": item["max_temp_c"],
                        "source": "open-meteo-archive",
                    },
                    f"{code}/research actuals",
                )
            captured_at = max(
                (item.get("fetched_at", item["run_at"]) for item in batches),
                default=current_time,
            )
            for target, _cutoff in due:
                try:
                    nowcast = _build_nowcast_from_session(
                        session,
                        code,
                        airport,
                        target,
                        captured_at,
                        [],
                    )
                    counts["forecast_snapshots"] += _record_forecast_snapshot(
                        session,
                        code,
                        airport,
                        target,
                        captured_at,
                        nowcast,
                    )
                except Exception as exc:
                    print(f"WARN {code}/research checkpoint journal/{target}: {exc}")
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
    metar_rows = recent_metars(
        airport_code,
        hours=48,
        attempts=1,
        timeout=5,
    )
    taf_rows = recent_tafs([airport_code], attempts=1, timeout=5) if include_taf else []
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
            lambda item: {key: value for key, value in item.items() if key != "observed_at"},
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


def in_critical_window(airport: dict, now: datetime) -> bool:
    """Return whether an airport is inside its configured local decision window."""
    configured = airport.get("critical_window_local")
    if not isinstance(configured, (list, tuple)) or len(configured) != 2:
        return False
    local = now.astimezone(ZoneInfo(airport["timezone"]))

    def minutes(value: object) -> int:
        hour, minute = str(value).split(":", maxsplit=1)
        return int(hour) * 60 + int(minute)

    start, end = (minutes(value) for value in configured)
    current = local.hour * 60 + local.minute
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def collect_live_decision_checkpoints(
    airport_codes: list[str] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Persist a fresh METAR-conditioned decision view only near airport peaks."""
    init_db()
    captured_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    catalog = trading_airports()
    requested = airport_codes or list(catalog)
    due_codes = [
        code
        for code in requested
        if code in catalog and in_critical_window(catalog[code], captured_at)
    ]
    counts = {
        "airports_due": len(due_codes),
        "observations": 0,
        "taf_reports": 0,
        "market_prices": 0,
        "forecast_snapshots": 0,
        "signals": 0,
        "strategy_snapshots": 0,
    }
    if not due_codes:
        return counts
    try:
        fetched_tafs = recent_tafs(due_codes, attempts=2, timeout=10)
    except Exception as exc:
        print(f"WARN live-decision TAF batch: {exc}")
        fetched_tafs = []
    with Session() as session:
        for code in due_codes:
            airport = catalog[code]
            try:
                metar_rows = recent_metars(
                    code,
                    hours=48,
                    attempts=2,
                    timeout=10,
                )
            except Exception as exc:
                print(f"WARN {code}/live-decision METAR: {exc}")
                metar_rows = []
            counts["observations"] += _upsert_batch(
                session,
                Observation,
                metar_rows,
                lambda item: {"airport": code, "observed_at": item["observed_at"]},
                lambda item: {key: value for key, value in item.items() if key != "observed_at"},
                f"{code}/live-decision METAR",
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
                f"{code}/live-decision TAF",
            )
            local_target = captured_at.astimezone(ZoneInfo(airport["timezone"])).date()
            try:
                market_rows = polymarket_prices(airport, local_target)
            except Exception as exc:
                print(f"WARN {code}/live-decision Polymarket: {exc}")
                market_rows = []
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
                f"{code}/live-decision Polymarket",
            )
            snapshot_at = (
                max(row["captured_at"] for row in market_rows) if market_rows else captured_at
            )
            try:
                nowcast = _build_nowcast_from_session(
                    session,
                    code,
                    airport,
                    local_target,
                    snapshot_at,
                    market_rows,
                )
                counts["forecast_snapshots"] += _record_forecast_snapshot(
                    session,
                    code,
                    airport,
                    local_target,
                    snapshot_at,
                    nowcast,
                )
                if market_rows:
                    counts["signals"] += _record_signal_snapshots(
                        session,
                        code,
                        airport,
                        market_rows,
                        nowcast=nowcast,
                    )
                    counts["strategy_snapshots"] += _record_strategy_snapshots(
                        session,
                        code,
                        airport,
                        market_rows,
                        nowcast,
                    )
            except Exception as exc:
                print(f"WARN {code}/live-decision snapshot: {exc}")
            session.commit()
    return counts


def backfill(days: int = 365, airport_codes: list[str] | None = None) -> dict[str, int]:
    init_db()
    # Reanalysis products can arrive several days late. A six-day safety margin
    # prevents a whole first-time backfill from failing on incomplete recent data.
    end = date.today() - timedelta(days=6)
    start = end - timedelta(days=days - 1)
    counts = {"forecasts": 0, "actuals": 0}
    catalog = research_airports()
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
                            "model_run_at": item.get("model_run_at"),
                            "available_at": item.get("available_at"),
                            "fetched_at": item.get("fetched_at"),
                            "provenance_status": item.get("provenance_status"),
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


def backfill_market_history(
    days: int = 30,
    airport_codes: list[str] | None = None,
) -> dict[str, int]:
    """Sample historical Polymarket prices at fixed D-1 and D0 decision times."""
    init_db()
    catalog = airports()
    selected_codes = airport_codes or list(trading_airports())
    counts = {"market_prices": 0, "airport_days": 0}
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=max(1, days) - 1)
    with Session() as session:
        for code in selected_codes:
            airport = catalog[code]
            zone = ZoneInfo(airport["timezone"])
            for offset in range((end - start).days + 1):
                target = start + timedelta(days=offset)
                sample_times = [
                    datetime(
                        target.year,
                        target.month,
                        target.day,
                        20,
                        tzinfo=zone,
                    ).astimezone(timezone.utc)
                    - timedelta(days=1),
                    datetime(
                        target.year,
                        target.month,
                        target.day,
                        10,
                        tzinfo=zone,
                    ).astimezone(timezone.utc),
                ]
                try:
                    rows = polymarket_historical_prices(airport, target, sample_times)
                except Exception as exc:
                    print(f"WARN {code}/historical market/{target}: {exc}")
                    continue
                stored = _upsert_batch(
                    session,
                    MarketSnapshot,
                    rows,
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
                    f"{code}/historical market/{target}",
                )
                counts["market_prices"] += stored
                counts["airport_days"] += int(stored > 0)
                session.commit()
                time.sleep(0.25)
    return counts
