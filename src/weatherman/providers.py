from __future__ import annotations

import json
import calendar
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .settings import settings

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
METAR_URL = "https://aviationweather.gov/api/data/metar"
TAF_URL = "https://aviationweather.gov/api/data/taf"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"

MONTH_SLUGS = (
    "",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _get(url: str, params: dict[str, Any] | None = None) -> dict | list:
    last_error: Exception | None = None
    with httpx.Client(
        timeout=settings.timeout,
        follow_redirects=True,
        headers={"User-Agent": "Weatherman/9.3 temperature-market research"},
    ) as client:
        for attempt in range(5):
            try:
                response = client.get(url, params=params)
                if response.status_code == 204:
                    return []
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                if not retryable or attempt == 4:
                    raise
                retry_after = None
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                print(f"WARN temporary API error; retrying in {delay:.0f}s")
                time.sleep(delay)
    if last_error:
        raise last_error
    raise RuntimeError("API request failed without a response")


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
            "horizon": _forecast_horizon(run_at, date.fromisoformat(day), airport["timezone"]),
        }
        for day, value in zip(daily.get("time", []), daily.get("temperature_2m_max", []))
        if value is not None
    ]


def _forecast_horizon(run_at: datetime, target_date: date, timezone_name: str) -> str:
    local_run = run_at.astimezone(ZoneInfo(timezone_name))
    if target_date == local_run.date() + timedelta(days=1):
        return "D-1"
    if target_date > local_run.date() + timedelta(days=1):
        return "D-2+"
    if target_date == local_run.date() and local_run.hour <= 10:
        return "D0-morning"
    return "Live"


def open_meteo_hourly(airport: dict, model: str, days: int = 3) -> list[dict]:
    variables = [
        "temperature_2m",
        "dew_point_2m",
        "cloud_cover",
        "wind_speed_10m",
        "wind_direction_10m",
        "shortwave_radiation",
        "temperature_850hPa",
    ]
    try:
        payload = _get(
            FORECAST_URL,
            {
                "latitude": airport["latitude"],
                "longitude": airport["longitude"],
                "hourly": ",".join(variables),
                "timezone": "UTC",
                "forecast_days": days,
                "models": model,
            },
        )
    except httpx.HTTPStatusError:
        # Some regional models do not expose 850 hPa. The surface-based
        # nowcast remains useful and should not be discarded.
        variables = variables[:-1]
        payload = _get(
            FORECAST_URL,
            {
                "latitude": airport["latitude"],
                "longitude": airport["longitude"],
                "hourly": ",".join(variables),
                "timezone": "UTC",
                "forecast_days": days,
                "models": model,
            },
        )
    hourly = payload.get("hourly", {})
    run_at = datetime.now(timezone.utc)
    rows = []
    for index, timestamp in enumerate(hourly.get("time", [])):
        temp = hourly.get("temperature_2m", [None])[index]
        if temp is None:
            continue

        def value(name: str) -> float | None:
            values = hourly.get(name)
            item = values[index] if values and index < len(values) else None
            return float(item) if item is not None else None

        rows.append(
            {
                "model": model,
                "run_at": run_at,
                "valid_at": datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc),
                "temp_c": float(temp),
                "dewpoint_c": value("dew_point_2m"),
                "cloud_cover": value("cloud_cover"),
                "wind_kph": value("wind_speed_10m"),
                "wind_direction": value("wind_direction_10m"),
                "radiation_wm2": value("shortwave_radiation"),
                "temp_850hpa_c": value("temperature_850hPa"),
            }
        )
    return rows


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
            "horizon": _forecast_horizon(now, date.fromisoformat(day[:10]), airport["timezone"]),
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
            "horizon": "Legacy",
        }
        for day, value in zip(daily.get("time", []), daily.get("temperature_2m_max", []))
        if value is not None
    ]


def previous_run_d1(airport: dict, model: str, start: date, end: date) -> list[dict]:
    variable = "temperature_2m_previous_day1"
    payload = _get(
        PREVIOUS_RUNS_URL,
        {
            "latitude": airport["latitude"],
            "longitude": airport["longitude"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": variable,
            "timezone": airport["timezone"],
            "models": model,
        },
    )
    hourly = payload.get("hourly", {})
    maxima: dict[date, float] = {}
    for timestamp, value in zip(hourly.get("time", []), hourly.get(variable, [])):
        if value is None:
            continue
        target = date.fromisoformat(timestamp[:10])
        maxima[target] = max(maxima.get(target, float("-inf")), float(value))
    tz = ZoneInfo(airport["timezone"])
    rows = []
    for target, max_temp in maxima.items():
        # Noon one day before represents a consistent 24-hour information set.
        run_local = datetime.combine(target, datetime.min.time(), tzinfo=tz).replace(hour=12)
        rows.append(
            {
                "model": model,
                "run_at": run_local.astimezone(timezone.utc) - timedelta(days=1),
                "target_date": target,
                "max_temp_c": max_temp,
                "source": "previous-runs",
                "horizon": "D-1",
            }
        )
    return rows


def recent_metars(icao: str, hours: int = 24) -> list[dict]:
    payload = _get(METAR_URL, {"ids": icao, "format": "json", "hours": hours})
    rows = []
    for row in payload or []:
        observed = row.get("obsTime") or row.get("reportTime")
        if observed is None or row.get("temp") is None:
            continue
        if isinstance(observed, (int, float)):
            observed_at = datetime.fromtimestamp(observed, tz=timezone.utc)
        else:
            text = str(observed).replace("Z", "+00:00")
            observed_at = datetime.fromisoformat(text)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
        try:
            wind_direction = float(row["wdir"]) if row.get("wdir") is not None else None
        except (TypeError, ValueError):
            # Variable winds are commonly reported as VRB and have no single direction.
            wind_direction = None
        rows.append(
            {
                "observed_at": observed_at.astimezone(timezone.utc),
                "temp_c": float(row["temp"]),
                "dewpoint_c": float(row["dewp"]) if row.get("dewp") is not None else None,
                "wind_kph": (float(row["wspd"]) * 1.852 if row.get("wspd") is not None else None),
                "wind_direction": wind_direction,
                "raw": row.get("rawOb"),
            }
        )
    return sorted(rows, key=lambda item: item["observed_at"])


def _api_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _taf_group_datetime(issue_time: datetime, day: int, hour: int) -> datetime:
    """Resolve a DDHH TAF group around an issue time, including month rollover."""
    candidates: list[datetime] = []
    for month_offset in (-1, 0, 1):
        month_index = issue_time.year * 12 + issue_time.month - 1 + month_offset
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
        if day <= calendar.monthrange(year, month)[1]:
            candidates.append(datetime(year, month, day, hour, tzinfo=timezone.utc))
    return min(candidates, key=lambda candidate: abs(candidate - issue_time))


def _raw_taf_temperature(
    raw_taf: str, marker: str, issue_time: datetime
) -> tuple[float | None, datetime | None]:
    match = re.search(rf"\b{marker}(M?\d{{2}})/(\d{{2}})(\d{{2}})Z\b", raw_taf)
    if not match:
        return None, None
    token, day, hour = match.groups()
    value = -float(token[1:]) if token.startswith("M") else float(token)
    return value, _taf_group_datetime(issue_time, int(day), int(hour))


def _decoded_taf_temperatures(
    report: dict, issue_time: datetime
) -> dict[str, tuple[float | None, datetime | None]]:
    decoded: dict[str, tuple[float | None, datetime | None]] = {}
    for period in report.get("fcsts") or []:
        for item in period.get("temp") or []:
            marker = str(item.get("maxOrMin") or "").upper()
            value = item.get("sfcTemp")
            valid_at = _api_datetime(item.get("validTime"))
            if marker in {"MAX", "MIN"} and value is not None and valid_at is not None:
                decoded[marker] = (float(value), valid_at)
    raw_taf = str(report.get("rawTAF") or "")
    decoded.setdefault("MAX", _raw_taf_temperature(raw_taf, "TX", issue_time))
    decoded.setdefault("MIN", _raw_taf_temperature(raw_taf, "TN", issue_time))
    return decoded


def _taf_periods_json(report: dict) -> str:
    periods = []
    for period in report.get("fcsts") or []:
        periods.append(
            {
                "time_from": (
                    _api_datetime(period.get("timeFrom")).isoformat()
                    if _api_datetime(period.get("timeFrom"))
                    else None
                ),
                "time_to": (
                    _api_datetime(period.get("timeTo")).isoformat()
                    if _api_datetime(period.get("timeTo"))
                    else None
                ),
                "time_bec": (
                    _api_datetime(period.get("timeBec")).isoformat()
                    if _api_datetime(period.get("timeBec"))
                    else None
                ),
                "change": period.get("fcstChange"),
                "probability": period.get("probability"),
                "wind_direction": period.get("wdir"),
                "wind_speed_kt": period.get("wspd"),
                "wind_gust_kt": period.get("wgst"),
                "weather": period.get("wxString"),
                "visibility_sm": period.get("visib"),
                "clouds": period.get("clouds") or [],
            }
        )
    return json.dumps(periods, separators=(",", ":"))


def recent_tafs(icaos: str | list[str]) -> list[dict]:
    """Fetch the current decoded TAFs in one rate-limit-friendly request."""
    identifiers = [icaos] if isinstance(icaos, str) else list(icaos)
    if not identifiers:
        return []
    payload = _get(TAF_URL, {"ids": ",".join(identifiers), "format": "json"})
    collected_at = datetime.now(timezone.utc)
    rows = []
    for report in payload or []:
        issue_time = _api_datetime(report.get("issueTime"))
        valid_from = _api_datetime(report.get("validTimeFrom"))
        valid_to = _api_datetime(report.get("validTimeTo"))
        raw_taf = str(report.get("rawTAF") or "").strip()
        if issue_time is None or valid_from is None or valid_to is None or not raw_taf:
            continue
        temperatures = _decoded_taf_temperatures(report, issue_time)
        maximum, maximum_at = temperatures.get("MAX", (None, None))
        minimum, minimum_at = temperatures.get("MIN", (None, None))
        rows.append(
            {
                "airport": str(report.get("icaoId") or "").upper(),
                "issue_time": issue_time,
                "bulletin_time": _api_datetime(report.get("bulletinTime")),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "raw_taf": raw_taf,
                "is_amended": bool(re.search(r"^TAF\s+AMD\b", raw_taf)),
                "is_corrected": bool(re.search(r"^TAF\s+COR\b", raw_taf)),
                "max_temp_c": maximum,
                "max_temp_at": maximum_at,
                "min_temp_c": minimum,
                "min_temp_at": minimum_at,
                "periods_json": _taf_periods_json(report),
                "collected_at": collected_at,
                "source": "aviationweather.gov",
            }
        )
    return sorted(rows, key=lambda item: (item["airport"], item["issue_time"]))


def polymarket_event_slug(airport: dict, target: date) -> str:
    city = airport.get("market_city")
    if not city:
        return ""
    return (
        f"highest-temperature-in-{city}-on-{MONTH_SLUGS[target.month]}-{target.day}-{target.year}"
    )


def _json_array(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _temperature_range(label: str) -> tuple[float | None, float | None]:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*°?C", label, re.IGNORECASE)
    if not match:
        return None, None
    temperature = float(match.group(1))
    lowered = label.casefold()
    if "below" in lowered or "lower" in lowered:
        return None, temperature
    if "higher" in lowered or "above" in lowered:
        return temperature, None
    return temperature, temperature


def polymarket_prices(airport: dict, target: date) -> list[dict]:
    event_slug = polymarket_event_slug(airport, target)
    if not event_slug:
        return []
    try:
        event = _get(f"{POLYMARKET_GAMMA_URL}/events/slug/{event_slug}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return []
        raise
    if not isinstance(event, dict):
        return []
    captured_at = datetime.now(timezone.utc)
    rows = []
    for market in event.get("markets", []):
        outcomes = _json_array(market.get("outcomes"))
        prices = _json_array(market.get("outcomePrices"))
        tokens = _json_array(market.get("clobTokenIds"))
        try:
            yes_index = [str(outcome).casefold() for outcome in outcomes].index("yes")
            yes_price = float(prices[yes_index])
        except (ValueError, IndexError, TypeError):
            continue
        label = str(market.get("groupItemTitle") or market.get("question") or "")
        low, high = _temperature_range(label)
        if low is None and high is None:
            continue
        closed = bool(market.get("closed"))
        yes_won = yes_price >= 0.999 if closed else None
        rows.append(
            {
                "target_date": target,
                "event_slug": event_slug,
                "market_id": str(market["id"]),
                "market_slug": str(market.get("slug") or ""),
                "token_id": str(tokens[yes_index]) if yes_index < len(tokens) else None,
                "bucket_label": label,
                "bucket_low_c": low,
                "bucket_high_c": high,
                "yes_price": yes_price,
                "best_bid": _number(market.get("bestBid")),
                "best_ask": _number(market.get("bestAsk")),
                "spread": _number(market.get("spread")),
                "volume": _number(market.get("volumeNum") or market.get("volume")),
                "liquidity": _number(market.get("liquidityNum") or market.get("liquidity")),
                "closed": closed,
                "yes_won": yes_won,
                "resolution_source": event.get("resolutionSource"),
                "captured_at": captured_at,
            }
        )
    return rows
