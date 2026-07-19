from __future__ import annotations

import time
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
                    for item in open_meteo_hourly(airport, model, days):
                        _upsert(
                            session,
                            HourlyForecast,
                            {
                                "airport": code,
                                "model": item["model"],
                                "run_at": item["run_at"],
                                "valid_at": item["valid_at"],
                            },
                            {
                                "temp_c": item["temp_c"],
                                "dewpoint_c": item["dewpoint_c"],
                                "cloud_cover": item["cloud_cover"],
                                "wind_kph": item["wind_kph"],
                                "wind_direction": item["wind_direction"],
                                "radiation_wm2": item["radiation_wm2"],
                                "temp_850hpa_c": item["temp_850hpa_c"],
                            },
                        )
                        counts["hourly_forecasts"] += 1
                except Exception as exc:
                    print(f"WARN {code}/{model} hourly: {exc}")
            try:
                batches.extend(meteoblue_forecast(airport))
            except Exception as exc:
                print(f"WARN {code}/meteoblue: {exc}")
            for item in batches:
                _upsert(
                    session,
                    Forecast,
                    {
                        "airport": code,
                        "model": item["model"],
                        "run_at": item["run_at"],
                        "target_date": item["target_date"],
                    },
                    {
                        "max_temp_c": item["max_temp_c"],
                        "source": item["source"],
                        "horizon": item["horizon"],
                    },
                )
                counts["forecasts"] += 1
            try:
                for obs in recent_metars(code):
                    _upsert(
                        session,
                        Observation,
                        {"airport": code, "observed_at": obs.pop("observed_at")},
                        obs,
                    )
                    counts["observations"] += 1
            except Exception as exc:
                print(f"WARN {code}/METAR: {exc}")
            actual_end = date.today() - timedelta(days=6)
            actual_start = actual_end - timedelta(days=13)
            try:
                for item in historical_actuals(airport, actual_start, actual_end):
                    _upsert(
                        session,
                        DailyActual,
                        {"airport": code, "target_date": item["target_date"]},
                        {
                            "max_temp_c": item["max_temp_c"],
                            "source": "open-meteo-archive",
                        },
                    )
                    counts["actuals"] += 1
            except Exception as exc:
                print(f"WARN {code}/recent actuals: {exc}")
            for offset in range(-2, days):
                market_target = date.today() + timedelta(days=offset)
                try:
                    for item in polymarket_prices(airport, market_target):
                        market_keys = {
                            "market_id": item["market_id"],
                            "captured_at": item["captured_at"],
                        }
                        _upsert(
                            session,
                            MarketSnapshot,
                            market_keys,
                            {
                                "airport": code,
                                **{
                                    key: value
                                    for key, value in item.items()
                                    if key not in market_keys
                                },
                            },
                        )
                        counts["market_prices"] += 1
                except Exception as exc:
                    print(f"WARN {code}/Polymarket/{market_target}: {exc}")
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
                airport_actuals = 0
                for item in historical_actuals(airport, start, end):
                    _upsert(
                        session,
                        DailyActual,
                        {"airport": code, "target_date": item["target_date"]},
                        {"max_temp_c": item["max_temp_c"], "source": "open-meteo-archive"},
                    )
                    counts["actuals"] += 1
                    airport_actuals += 1
                print(f"OK {code}/actuals: {airport_actuals} days")
            except Exception as exc:
                print(f"WARN {code}/historical actuals: {exc}")
            for model in airport["models"]:
                try:
                    model_rows = 0
                    for item in previous_run_d1(airport, model, start, end):
                        _upsert(
                            session,
                            Forecast,
                            {
                                "airport": code,
                                "model": model,
                                "run_at": item["run_at"],
                                "target_date": item["target_date"],
                            },
                            {
                                "max_temp_c": item["max_temp_c"],
                                "source": item["source"],
                                "horizon": item["horizon"],
                            },
                        )
                        counts["forecasts"] += 1
                        model_rows += 1
                    print(f"OK {code}/{model}: {model_rows} days")
                except Exception as exc:
                    print(f"WARN {code}/{model} backfill: {exc}")
                # Keep the free data endpoint below burst-rate limits.
                time.sleep(1)
        session.commit()
    return counts
