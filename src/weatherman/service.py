from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import date, timedelta

from sqlalchemy import select

from .db import (
    DailyActual,
    Forecast,
    HourlyForecast,
    MarketSnapshot,
    Observation,
    Session,
    init_db,
)
from .providers import (
    historical_actuals,
    meteoblue_forecast,
    open_meteo_forecast,
    open_meteo_hourly,
    polymarket_prices,
    previous_run_d1,
    recent_metars,
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


def collect(airport_codes: list[str] | None = None, days: int = 3) -> dict[str, int]:
    init_db()
    counts = {
        "forecasts": 0,
        "hourly_forecasts": 0,
        "observations": 0,
        "market_prices": 0,
        "actuals": 0,
    }
    catalog = airports()
    with Session() as session:
        for code in airport_codes or list(catalog):
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
            for offset in range(-2, days):
                market_target = date.today() + timedelta(days=offset)
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
        session.commit()
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
