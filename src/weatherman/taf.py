from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd


@dataclass(frozen=True)
class TafGuidance:
    issue_time: datetime
    age_hours: float
    raw_taf: str
    is_amended: bool
    is_corrected: bool
    max_temp_c: float | None
    max_temp_at: datetime | None
    agreement: str
    temperature_difference_c: float | None
    center_adjustment_c: float
    spread_addition_c: float
    confidence_score: int
    heat_score_points: int
    heat_adjustment_c: float
    peak_wind_kph: float | None
    peak_wind_direction_deg: float | None
    peak_gust_kph: float | None
    cloud_risk: str
    precipitation_risk: bool
    thunderstorm_risk: bool
    signals: tuple[str, ...]
    temperature_influence_active: bool
    change_summary: str | None = None


def _utc(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _periods(value: object) -> list[dict]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _overlaps(start: pd.Timestamp, end: pd.Timestamp, period: dict) -> bool:
    period_start = _utc(period.get("time_from"))
    period_end = _utc(period.get("time_to"))
    if period_start is None or period_end is None:
        return False
    return period_start < end and period_end > start


def _circular_mean(values: list[float]) -> float | None:
    if not values:
        return None
    radians = [math.radians(value % 360) for value in values]
    sine = sum(math.sin(value) for value in radians) / len(radians)
    cosine = sum(math.cos(value) for value in radians) / len(radians)
    if abs(sine) < 1e-9 and abs(cosine) < 1e-9:
        return None
    return math.degrees(math.atan2(sine, cosine)) % 360


def _direction_in_sectors(direction: float, sectors: object) -> bool:
    for sector in sectors or []:
        if not isinstance(sector, (list, tuple)) or len(sector) != 2:
            continue
        start, end = float(sector[0]) % 360, float(sector[1]) % 360
        if start <= end and start <= direction <= end:
            return True
        if start > end and (direction >= start or direction <= end):
            return True
    return False


def _peak_conditions(
    row: pd.Series,
    timezone_name: str,
    target: date,
    as_of: datetime,
    wind_profile: dict | None,
) -> dict:
    timezone = ZoneInfo(timezone_name)
    peak_start = pd.Timestamp(datetime.combine(target, time(11), timezone))
    peak_end = pd.Timestamp(datetime.combine(target, time(19), timezone))
    as_of_utc = _utc(as_of)
    assert as_of_utc is not None
    as_of_local = as_of_utc.tz_convert(timezone_name)
    active_start = max(peak_start, as_of_local)
    if active_start >= peak_end:
        return {
            "wind_speed": None,
            "wind_direction": None,
            "wind_gust": None,
            "cloud_risk": "Heating window ended",
            "precipitation": False,
            "thunderstorm": False,
            "heat_points": 0,
            "heat_adjustment": 0.0,
            "signals": [
                "The TAF heating window has ended; its conditions no longer adjust today's peak"
            ],
        }
    overlapping = [
        period
        for period in _periods(row.get("periods_json"))
        if _overlaps(active_start.tz_convert("UTC"), peak_end.tz_convert("UTC"), period)
    ]
    directions: list[float] = []
    speeds: list[float] = []
    gusts: list[float] = []
    covers: list[str] = []
    weather: list[str] = []
    has_cb = False
    has_clear = False
    probability_values: list[int] = []
    for period in overlapping:
        direction = period.get("wind_direction")
        try:
            directions.append(float(direction))
        except (TypeError, ValueError):
            pass
        for key, destination in (
            ("wind_speed_kt", speeds),
            ("wind_gust_kt", gusts),
        ):
            try:
                destination.append(float(period[key]))
            except (KeyError, TypeError, ValueError):
                pass
        if period.get("probability") is not None:
            try:
                probability_values.append(int(period["probability"]))
            except (TypeError, ValueError):
                pass
        if period.get("weather"):
            weather.append(str(period["weather"]).upper())
        for cloud in period.get("clouds") or []:
            cover = str(cloud.get("cover") or "").upper()
            if cover:
                covers.append(cover)
            has_cb = has_cb or str(cloud.get("type") or "").upper() in {"CB", "TCU"}
            has_clear = has_clear or cover in {"NSC", "SKC", "CLR"}

    weather_text = " ".join(weather)
    thunderstorm = "TS" in weather_text or has_cb
    precipitation = any(token in weather_text for token in ("RA", "DZ", "SN", "SH", "GR"))
    if "OVC" in covers or "BKN" in covers:
        cloud_risk = "BKN/OVC near peak"
    elif "SCT" in covers:
        cloud_risk = "Scattered cloud near peak"
    elif has_clear:
        cloud_risk = "No significant cloud near peak"
    else:
        cloud_risk = "No peak cloud guidance"

    wind_direction = _circular_mean(directions)
    wind_speed = max(speeds) * 1.852 if speeds else None
    wind_gust = max(gusts) * 1.852 if gusts else None
    points = 0
    signals: list[str] = []
    if thunderstorm:
        points -= 10
        signals.append("TAF includes a thunderstorm/CB risk during the heating window")
    elif precipitation:
        points -= 6
        signals.append("TAF includes precipitation during the heating window")
    if cloud_risk == "BKN/OVC near peak":
        points -= 4
        signals.append("TAF expects broken or overcast cloud near the daily peak")
    elif cloud_risk == "No significant cloud near peak":
        points += 3
        signals.append("TAF expects no significant cloud near the daily peak")

    wind_profile = wind_profile or {}
    if wind_direction is not None and wind_speed is not None:
        if _direction_in_sectors(wind_direction, wind_profile.get("warm_sectors")):
            points += 2
            signals.append("TAF peak wind is in this airport's warm sector")
        elif _direction_in_sectors(wind_direction, wind_profile.get("cool_sectors")):
            points -= 3
            signals.append("TAF peak wind is in this airport's cooling sector")
    if wind_gust is not None and wind_gust >= 45:
        points -= 2
        signals.append(f"TAF gusts up to {wind_gust:.0f} km/h increase peak uncertainty")
    if probability_values:
        signals.append(
            f"Conditional TAF risks carry up to PROB{max(probability_values)}"
        )
    points = max(-12, min(6, points))
    return {
        "wind_speed": wind_speed,
        "wind_direction": wind_direction,
        "wind_gust": wind_gust,
        "cloud_risk": cloud_risk,
        "precipitation": precipitation,
        "thunderstorm": thunderstorm,
        "heat_points": points,
        "heat_adjustment": max(-0.35, min(0.20, points / 35)),
        "signals": signals,
    }


def _guidance_for_row(
    row: pd.Series,
    *,
    timezone_name: str,
    target: date,
    as_of: datetime,
    model_mean: float,
    wind_profile: dict | None,
    observed_cooling: bool,
) -> TafGuidance:
    issue = _utc(row.get("issue_time"))
    assert issue is not None
    as_of_utc = _utc(as_of)
    assert as_of_utc is not None
    age_hours = max(0.0, (as_of_utc - issue).total_seconds() / 3600)
    maximum = float(row.max_temp_c) if pd.notna(row.get("max_temp_c")) else None
    maximum_at_timestamp = _utc(row.get("max_temp_at"))
    if (
        maximum_at_timestamp is not None
        and maximum_at_timestamp.tz_convert(timezone_name).date() != target
    ):
        maximum = None
        maximum_at_timestamp = None
    maximum_at = maximum_at_timestamp.to_pydatetime() if maximum_at_timestamp is not None else None
    difference = maximum - model_mean if maximum is not None else None
    temperature_influence_active = maximum is not None
    temperature_influence_expired = False
    if difference is None:
        agreement = "Neutral · no TX issued"
        confidence_score = 55
        center_adjustment = 0.0
        spread_addition = 0.0
    elif abs(difference) <= 1:
        agreement = "Supports model"
        confidence_score = 90
        center_adjustment = 0.0
        spread_addition = 0.0
    elif abs(difference) <= 2:
        agreement = "Mild conflict"
        confidence_score = 62
        center_adjustment = max(-0.20, min(0.20, 0.10 * difference))
        spread_addition = 0.20
    else:
        agreement = "Contradicts model"
        confidence_score = 30
        center_adjustment = 0.25 if difference > 0 else -0.25
        spread_addition = 0.45
    if age_hours > 12:
        confidence_score = max(20, confidence_score - 15)
        center_adjustment *= 0.5
    conditions = _peak_conditions(row, timezone_name, target, as_of, wind_profile)
    if conditions["thunderstorm"] or conditions["precipitation"]:
        spread_addition = max(spread_addition, 0.25)
    maximum_at_utc = _utc(maximum_at)
    if (
        maximum_at_utc is not None
        and as_of_utc >= maximum_at_utc
        and observed_cooling
    ):
        temperature_influence_active = False
        temperature_influence_expired = True
        center_adjustment = 0.0
        spread_addition = 0.0
        agreement = f"{agreement} · TX passed"
    center_adjustment = max(-0.25, min(0.25, center_adjustment))
    signals = list(conditions["signals"])
    if maximum is not None:
        signals.insert(
            0,
            f"TAF TX is {maximum:.0f} °C ({difference:+.1f} °C versus model consensus)",
        )
    else:
        signals.insert(0, "This TAF does not contain an explicit TX maximum")
    if temperature_influence_expired:
        signals.insert(
            1,
            "TAF TX influence is disabled because its valid peak time passed and METAR is cooling",
        )
    return TafGuidance(
        issue_time=issue.to_pydatetime(),
        age_hours=age_hours,
        raw_taf=str(row.get("raw_taf") or ""),
        is_amended=bool(row.get("is_amended", False)),
        is_corrected=bool(row.get("is_corrected", False)),
        max_temp_c=maximum,
        max_temp_at=maximum_at,
        agreement=agreement,
        temperature_difference_c=difference,
        center_adjustment_c=center_adjustment,
        spread_addition_c=spread_addition,
        confidence_score=confidence_score,
        heat_score_points=int(conditions["heat_points"]),
        heat_adjustment_c=float(conditions["heat_adjustment"]),
        peak_wind_kph=conditions["wind_speed"],
        peak_wind_direction_deg=conditions["wind_direction"],
        peak_gust_kph=conditions["wind_gust"],
        cloud_risk=str(conditions["cloud_risk"]),
        precipitation_risk=bool(conditions["precipitation"]),
        thunderstorm_risk=bool(conditions["thunderstorm"]),
        signals=tuple(signals),
        temperature_influence_active=temperature_influence_active,
    )


def build_taf_guidance(
    tafs: pd.DataFrame,
    *,
    timezone_name: str,
    target: date,
    as_of: datetime,
    model_mean: float,
    wind_profile: dict | None = None,
    observed_cooling: bool = False,
) -> TafGuidance | None:
    if tafs is None or tafs.empty:
        return None
    available = tafs.copy()
    for column in ("issue_time", "valid_from", "valid_to", "collected_at"):
        if column in available:
            available[column] = pd.to_datetime(available[column], utc=True, errors="coerce")
    as_of_utc = _utc(as_of)
    assert as_of_utc is not None
    timezone = ZoneInfo(timezone_name)
    target_start = pd.Timestamp(datetime.combine(target, time.min, timezone)).tz_convert("UTC")
    target_end = pd.Timestamp(datetime.combine(target, time.max, timezone)).tz_convert("UTC")
    available = available[
        (available.issue_time <= as_of_utc)
        & (available.valid_from <= target_end)
        & (available.valid_to >= target_start)
    ].sort_values(["issue_time", "collected_at"])
    if available.empty:
        return None
    latest = _guidance_for_row(
        available.iloc[-1],
        timezone_name=timezone_name,
        target=target,
        as_of=as_of,
        model_mean=model_mean,
        wind_profile=wind_profile,
        observed_cooling=observed_cooling,
    )
    if len(available) < 2:
        return latest
    previous = _guidance_for_row(
        available.iloc[-2],
        timezone_name=timezone_name,
        target=target,
        as_of=as_of,
        model_mean=model_mean,
        wind_profile=wind_profile,
        observed_cooling=observed_cooling,
    )
    changes: list[str] = []
    if latest.max_temp_c is not None and previous.max_temp_c is not None:
        tx_change = latest.max_temp_c - previous.max_temp_c
        if abs(tx_change) >= 0.5:
            changes.append(f"TX changed {tx_change:+.0f} °C")
    if latest.thunderstorm_risk != previous.thunderstorm_risk:
        changes.append(
            "thunderstorm risk added"
            if latest.thunderstorm_risk
            else "thunderstorm risk removed"
        )
    if latest.precipitation_risk != previous.precipitation_risk:
        changes.append(
            "precipitation risk added"
            if latest.precipitation_risk
            else "precipitation risk removed"
        )
    if latest.cloud_risk != previous.cloud_risk:
        changes.append(f"peak cloud guidance changed to {latest.cloud_risk.lower()}")
    if latest.peak_gust_kph is not None and previous.peak_gust_kph is not None:
        gust_change = latest.peak_gust_kph - previous.peak_gust_kph
        if abs(gust_change) >= 8:
            changes.append(f"peak gust changed {gust_change:+.0f} km/h")
    summary = "; ".join(changes) if changes else "No material change from the previous TAF"
    return replace(latest, change_summary=summary)


def taf_verification_frame(
    tafs: pd.DataFrame,
    actuals: pd.DataFrame,
    timezone_by_airport: dict[str, str],
) -> pd.DataFrame:
    """Create leakage-free TAF TX checks by airport and issuance timing."""
    if tafs.empty or actuals.empty or "max_temp_c" not in tafs:
        return pd.DataFrame()
    frame = tafs.dropna(subset=["max_temp_c", "max_temp_at"]).copy()
    if frame.empty:
        return pd.DataFrame()
    frame["issue_time"] = pd.to_datetime(frame.issue_time, utc=True)
    frame["max_temp_at"] = pd.to_datetime(frame.max_temp_at, utc=True)

    def timing(row: pd.Series) -> pd.Series:
        timezone = ZoneInfo(timezone_by_airport.get(str(row.airport), "UTC"))
        issue_local = row.issue_time.tz_convert(timezone)
        maximum_local = row.max_temp_at.tz_convert(timezone)
        target_date = maximum_local.date()
        if issue_local.date() < target_date:
            label = "D-1"
        elif issue_local.hour < 12:
            label = "D0 morning"
        else:
            label = "Live"
        return pd.Series({"target_date": target_date, "timing": label})

    frame[["target_date", "timing"]] = frame.apply(timing, axis=1)
    frame = frame.sort_values("issue_time").drop_duplicates(
        ["airport", "target_date", "timing"], keep="last"
    )
    actual_frame = actuals.copy()
    actual_frame["target_date"] = pd.to_datetime(actual_frame.target_date).dt.date
    merged = frame.merge(
        actual_frame[["airport", "target_date", "max_temp_c"]],
        on=["airport", "target_date"],
        suffixes=("_taf", "_actual"),
    )
    if merged.empty:
        return merged
    merged["error"] = merged.max_temp_c_taf - merged.max_temp_c_actual
    merged["abs_error"] = merged.error.abs()
    return merged


def taf_verification_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    return (
        scored.groupby(["airport", "timing"], as_index=False)
        .agg(
            n=("error", "size"),
            bias=("error", "mean"),
            mae=("abs_error", "mean"),
            exact_hit=("abs_error", lambda values: (values < 0.5).mean()),
            within_1c=("abs_error", lambda values: (values <= 1).mean()),
        )
        .sort_values(["airport", "timing"])
    )
