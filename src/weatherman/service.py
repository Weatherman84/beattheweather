from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from .db import DailyActual, Forecast, Observation, Session, init_db
from .providers import (
    historical_actuals,
    historical_model,
    latest_metar,
    meteoblue_forecast,
    open_meteo_forecast,
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
    counts = {"forecasts": 0, "observations": 0}
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
                    {"max_temp_c": item["max_temp_c"], "source": item["source"]},
                )
                counts["forecasts"] += 1
            try:
                obs = latest_metar(code)
                if obs:
                    _upsert(
                        session,
                        Observation,
                        {"airport": code, "observed_at": obs.pop("observed_at")},
                        obs,
                    )
                    counts["observations"] += 1
            except Exception as exc:
                print(f"WARN {code}/METAR: {exc}")
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
                for item in historical_actuals(airport, start, end):
                    _upsert(
                        session,
                        DailyActual,
                        {"airport": code, "target_date": item["target_date"]},
                        {"max_temp_c": item["max_temp_c"], "source": "open-meteo-archive"},
                    )
                    counts["actuals"] += 1
            except Exception as exc:
                print(f"WARN {code}/historical actuals: {exc}")
            for model in airport["models"]:
                try:
                    for item in historical_model(airport, model, start, end):
                        _upsert(
                            session,
                            Forecast,
                            {
                                "airport": code,
                                "model": model,
                                "run_at": item["run_at"],
                                "target_date": item["target_date"],
                            },
                            {"max_temp_c": item["max_temp_c"], "source": item["source"]},
                        )
                        counts["forecasts"] += 1
                except Exception as exc:
                    print(f"WARN {code}/{model} backfill: {exc}")
        session.commit()
    return counts
