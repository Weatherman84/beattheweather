from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

from .settings import settings

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
METAR_URL = "https://aviationweather.gov/api/data/metar"


def _get(url: str, params: dict[str, Any] | None = None) -> dict | list:
    with httpx.Client(timeout=settings.timeout, follow_redirects=True) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def open_meteo_forecast(airport: dict, model: str, days: int = 3) -> list[dict]:
    payload = _get(
        FORECAST_URL,
        {
            "latitude": airport["latitude"],
            "longitude": airport["longitude"],
            "daily": "temperature_2m_max",
            "timezone": airport["timezone"],
            "forecast_days": days,
            "models": model,
        },
    )
    daily = payload.get("daily", {})
    run_at = datetime.now(timezone.utc)
    return [
        {
            "model": model,
            "run_at": run_at,
            "target_date": date.fromisoformat(day),
            "max_temp_c": float(value),
            "source": "open-meteo",
        }
        for day, value in zip(daily.get("time", []), daily.get("temperature_2m_max", []))
        if value is not None
    ]


def meteoblue_forecast(airport: dict) -> list[dict]:
    if not settings.meteoblue_api_key or not settings.meteoblue_url_template:
        return []
    url = settings.meteoblue_url_template.format(
        lat=airport["latitude"],
        lon=airport["longitude"],
        elevation=airport["elevation_m"],
        apikey=settings.meteoblue_api_key,
    )
    payload = _get(url)
    daily = payload.get("data_day", {})
    times = daily.get("time", [])
    temps = daily.get("temperature_max", [])
    now = datetime.now(timezone.utc)
    return [
        {
            "model": "meteoblue",
            "run_at": now,
            "target_date": date.fromisoformat(day[:10]),
            "max_temp_c": float(value),
            "source": "meteoblue",
        }
        for day, value in zip(times, temps)
        if value is not None
    ]


def historical_actuals(airport: dict, start: date, end: date) -> list[dict]:
    payload = _get(
        ARCHIVE_URL,
        {
            "latitude": airport["latitude"],
            "longitude": airport["longitude"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max",
            "timezone": airport["timezone"],
        },
    )
    daily = payload.get("daily", {})
    return [
        {"target_date": date.fromisoformat(day), "max_temp_c": float(value)}
        for day, value in zip(daily.get("time", []), daily.get("temperature_2m_max", []))
        if value is not None
    ]


def historical_model(airport: dict, model: str, start: date, end: date) -> list[dict]:
    payload = _get(
        HISTORICAL_FORECAST_URL,
        {
            "latitude": airport["latitude"],
            "longitude": airport["longitude"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max",
            "timezone": airport["timezone"],
            "models": model,
        },
    )
    daily = payload.get("daily", {})
    # Historical Forecast API is a reconstructed archive; label it explicitly.
    return [
        {
            "model": model,
            "run_at": datetime.combine(
                date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc
            ),
            "target_date": date.fromisoformat(day),
            "max_temp_c": float(value),
            "source": "historical-forecast",
        }
        for day, value in zip(daily.get("time", []), daily.get("temperature_2m_max", []))
        if value is not None
    ]


def latest_metar(icao: str) -> dict | None:
    payload = _get(METAR_URL, {"ids": icao, "format": "json", "hours": 3})
    if not payload:
        return None
    row = payload[0]
    return {
        "observed_at": datetime.fromtimestamp(row["obsTime"], tz=timezone.utc),
        "temp_c": float(row["temp"]),
        "dewpoint_c": row.get("dewp"),
        "wind_kph": float(row["wspd"]) * 1.852 if row.get("wspd") is not None else None,
        "raw": row.get("rawOb"),
    }
