from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .analytics import (
    Consensus,
    DayStatus,
    HeatSpikeAssessment,
    assess_day_status,
    condition_probability_range,
    consensus,
    heat_spike_assessment,
    model_metrics,
    model_weight_map,
    resolved_market_range,
    score_frame,
)
from .taf import TafGuidance, build_taf_guidance


@dataclass(frozen=True)
class LiveNowcast:
    current: pd.DataFrame
    corrected: Consensus
    heat: HeatSpikeAssessment
    day_status: DayStatus
    probabilities: dict[int, float]
    observed_max: float | None
    heating_rate: float | None
    expected_now: float | None
    cloud_cover: float | None
    wind_speed_kph: float | None
    wind_direction_deg: float | None
    wind_source: str | None
    temp_850_c: float | None
    radiation_wm2: float | None
    remaining_rise_c: float | None
    future_radiation_max: float | None
    forecast_confidence: int
    confidence_factors: dict[str, float]
    model_weights: dict[str, float]
    taf_guidance: TafGuidance | None


def local_observations(
    frame: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result["observed_at"] = pd.to_datetime(result.observed_at, utc=True)
    if as_of is not None:
        result = result[result.observed_at <= pd.Timestamp(as_of).tz_convert("UTC")]
    result["local_at"] = result.observed_at.dt.tz_convert(timezone_name)
    return result[result.local_at.dt.date == target].sort_values("observed_at")


def _hourly_for_target(
    frame: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result["valid_at"] = pd.to_datetime(result.valid_at, utc=True)
    result["run_at"] = pd.to_datetime(result.run_at, utc=True)
    as_of_utc = pd.Timestamp(as_of).tz_convert("UTC")
    result = result[result.run_at <= as_of_utc]
    result["local_valid"] = result.valid_at.dt.tz_convert(timezone_name)
    return result[result.local_valid.dt.date == target]


def hourly_context(
    frame: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    result = _hourly_for_target(frame, timezone_name, target, as_of)
    if result.empty:
        return None, None, None, None, None, None
    result = result.sort_values("run_at").drop_duplicates(
        ["model", "valid_at"], keep="last"
    )
    local_now = as_of.astimezone(ZoneInfo(timezone_name))
    reference = (
        local_now
        if target == local_now.date()
        else datetime(target.year, target.month, target.day, 14, tzinfo=ZoneInfo(timezone_name))
    )
    reference_utc = pd.Timestamp(reference).tz_convert("UTC")
    result["distance"] = (result.valid_at - reference_utc).abs()
    nearest = result.sort_values("distance").drop_duplicates("model", keep="first")

    def median(column: str) -> float | None:
        if column not in nearest:
            return None
        values = nearest[column].dropna()
        return float(values.median()) if not values.empty else None

    def circular_mean(column: str) -> float | None:
        if column not in nearest:
            return None
        values = nearest[column].dropna()
        if values.empty:
            return None
        radians = values.astype(float).map(math.radians)
        sine = radians.map(math.sin).mean()
        cosine = radians.map(math.cos).mean()
        if abs(sine) < 1e-9 and abs(cosine) < 1e-9:
            return None
        return float(math.degrees(math.atan2(sine, cosine)) % 360)

    return (
        median("temp_c"),
        median("cloud_cover"),
        median("temp_850hpa_c"),
        median("radiation_wm2"),
        median("wind_kph"),
        circular_mean("wind_direction"),
    )


def remaining_heating_context(
    frame: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
) -> tuple[float | None, float | None]:
    result = _hourly_for_target(frame, timezone_name, target, as_of)
    if result.empty:
        return None, None
    reference_utc = pd.Timestamp(as_of).tz_convert("UTC")
    rises: list[float] = []
    future_radiation: list[float] = []
    for _, model_frame in result.groupby("model"):
        latest_run = model_frame.run_at.max()
        model_frame = model_frame[model_frame.run_at == latest_run].sort_values("valid_at")
        if model_frame.empty:
            continue
        nearest_index = (model_frame.valid_at - reference_utc).abs().idxmin()
        expected_now = float(model_frame.loc[nearest_index, "temp_c"])
        future = model_frame[
            model_frame.valid_at >= reference_utc - timedelta(minutes=30)
        ]
        if future.empty:
            rises.append(0.0)
            future_radiation.append(0.0)
            continue
        rises.append(max(0.0, float(future.temp_c.max()) - expected_now))
        radiation_values = future.radiation_wm2.dropna()
        if not radiation_values.empty:
            future_radiation.append(float(radiation_values.max()))
    remaining_rise = max(rises) if rises else None
    radiation_max = max(future_radiation) if future_radiation else None
    return remaining_rise, radiation_max


def model_run_trend(
    frame: pd.DataFrame,
    target: date,
    as_of: datetime,
) -> float | None:
    if frame.empty:
        return None
    recent = frame[
        (pd.to_datetime(frame.target_date).dt.date == target)
        & frame.source.isin(["open-meteo", "meteoblue"])
    ].copy()
    if recent.empty:
        return None
    recent["run_at"] = pd.to_datetime(recent.run_at, utc=True)
    recent = recent[recent.run_at <= pd.Timestamp(as_of).tz_convert("UTC")]
    changes = []
    for _, model_frame in recent.groupby("model"):
        values = model_frame.sort_values("run_at").max_temp_c.tail(2).tolist()
        if len(values) == 2:
            changes.append(float(values[-1] - values[-2]))
    return float(pd.Series(changes).median()) if changes else None


def build_live_nowcast(
    *,
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    observations: pd.DataFrame,
    hourly: pd.DataFrame,
    markets: pd.DataFrame,
    tafs: pd.DataFrame | None = None,
    timezone_name: str,
    target: date,
    as_of: datetime,
    wind_profile: dict | None = None,
) -> LiveNowcast | None:
    if forecasts.empty:
        return None
    as_of_utc = pd.Timestamp(as_of).tz_convert("UTC")
    available = forecasts.copy()
    available["run_at"] = pd.to_datetime(available.run_at, utc=True)
    available = available[available.run_at <= as_of_utc]
    current = available[
        (pd.to_datetime(available.target_date).dt.date == target)
        & available.source.isin(["open-meteo", "meteoblue"])
    ].copy()
    if current.empty:
        return None
    current = current.sort_values("run_at").drop_duplicates("model", keep="last")

    d1 = available[available.horizon == "D-1"].copy()
    if not d1.empty:
        d1 = d1[pd.to_datetime(d1.target_date).dt.date < target]
    prior_actuals = actuals.copy()
    if not prior_actuals.empty:
        prior_actuals = prior_actuals[
            pd.to_datetime(prior_actuals.target_date).dt.date < target
        ]
    d1_scored = score_frame(d1, prior_actuals)
    if not d1_scored.empty:
        d1_scored["target_date"] = pd.to_datetime(d1_scored.target_date).dt.date
        d1_scored = d1_scored[
            d1_scored.target_date >= target - timedelta(days=90)
        ]
    d1_metrics = model_metrics(d1_scored)
    bias_map = dict(zip(d1_metrics.model, d1_metrics.bias)) if not d1_metrics.empty else {}
    weight_map = model_weight_map(d1_scored)
    fallback_weight = (
        float(pd.Series(weight_map.values()).median()) if weight_map else 1.0
    )
    current["d1_bias"] = current.model.map(bias_map).fillna(0).astype(float)
    current["corrected_max"] = current.max_temp_c - current.d1_bias
    current["model_weight"] = current.model.map(weight_map).fillna(fallback_weight).astype(float)
    current["model_weight"] = current.model_weight / current.model_weight.sum()
    corrected = consensus(
        current.max_temp_c.tolist(),
        current.d1_bias.tolist(),
        weights=current.model_weight.tolist(),
    )
    wind_profile = wind_profile or {}
    taf_guidance = build_taf_guidance(
        tafs if tafs is not None else pd.DataFrame(),
        timezone_name=timezone_name,
        target=target,
        as_of=as_of,
        model_mean=corrected.mean,
        wind_profile=wind_profile,
    )

    obs_today = local_observations(observations, timezone_name, target, as_of)
    latest_obs = obs_today.iloc[-1] if not obs_today.empty else None
    observed_max = float(obs_today.temp_c.max()) if not obs_today.empty else None
    heating_rate = None
    if len(obs_today) >= 2:
        latest_time = pd.Timestamp(obs_today.observed_at.iloc[-1])
        recent_obs = obs_today[obs_today.observed_at >= latest_time - timedelta(hours=3)]
        elapsed = (
            recent_obs.observed_at.iloc[-1] - recent_obs.observed_at.iloc[0]
        ).total_seconds() / 3600
        if elapsed > 0:
            heating_rate = float(
                (recent_obs.temp_c.iloc[-1] - recent_obs.temp_c.iloc[0]) / elapsed
            )

    (
        expected_now,
        cloud_cover,
        temp_850,
        radiation,
        model_wind_speed,
        model_wind_direction,
    ) = hourly_context(hourly, timezone_name, target, as_of)
    remaining_rise, future_radiation = remaining_heating_context(
        hourly, timezone_name, target, as_of
    )
    observation_age_hours = None
    if latest_obs is not None:
        observation_age_hours = max(
            0.0,
            (as_of_utc - pd.Timestamp(latest_obs.observed_at)).total_seconds() / 3600,
        )
    trend = model_run_trend(available, target, as_of)
    recent_baseline = None
    if not prior_actuals.empty:
        past = prior_actuals.sort_values("target_date")
        recent_baseline = float(past.max_temp_c.tail(14).median())

    local_now = as_of.astimezone(ZoneInfo(timezone_name))
    observed_wind_speed = None
    observed_wind_direction = None
    if latest_obs is not None:
        if "wind_kph" in latest_obs.index and pd.notna(latest_obs.wind_kph):
            observed_wind_speed = float(latest_obs.wind_kph)
        if "wind_direction" in latest_obs.index and pd.notna(latest_obs.wind_direction):
            observed_wind_direction = float(latest_obs.wind_direction)
    if (
        observed_wind_speed is not None
        and observation_age_hours is not None
        and observation_age_hours <= 2
    ):
        wind_speed = observed_wind_speed
        # Keep VRB/unknown METAR direction unknown instead of silently mixing it
        # with a model direction and labelling the hybrid as an observation.
        wind_direction = observed_wind_direction
        wind_source = "METAR"
    else:
        wind_speed = model_wind_speed
        wind_direction = model_wind_direction
        wind_source = "model"
    heat = heat_spike_assessment(
        forecast_mean=corrected.mean,
        recent_baseline=recent_baseline,
        run_trend=trend,
        model_spread=corrected.spread,
        observed_temp=float(latest_obs.temp_c) if latest_obs is not None else None,
        observed_dewpoint=(
            float(latest_obs.dewpoint_c)
            if latest_obs is not None and pd.notna(latest_obs.dewpoint_c)
            else None
        ),
        expected_temp_now=expected_now if target == local_now.date() else None,
        heating_rate=heating_rate,
        cloud_cover=cloud_cover,
        wind_speed_kph=wind_speed,
        wind_direction_deg=wind_direction,
        warm_wind_sectors=wind_profile.get("warm_sectors"),
        cool_wind_sectors=wind_profile.get("cool_sectors"),
        wind_source=wind_source,
        guidance_score_points=(
            taf_guidance.heat_score_points if taf_guidance is not None else 0
        ),
        guidance_adjustment_c=(
            taf_guidance.heat_adjustment_c if taf_guidance is not None else 0.0
        ),
        guidance_signals=(taf_guidance.signals if taf_guidance is not None else None),
    )
    taf_center_adjustment = (
        taf_guidance.center_adjustment_c if taf_guidance is not None else 0.0
    )
    taf_spread_addition = (
        taf_guidance.spread_addition_c if taf_guidance is not None else 0.0
    )
    unconditioned = consensus(
        (current.corrected_max + heat.adjustment_c + taf_center_adjustment).tolist(),
        weights=current.model_weight.tolist(),
        sigma_floor=0.65 + taf_spread_addition,
    )
    resolution = resolved_market_range(markets)
    day_status = assess_day_status(
        target_date=target,
        local_now=local_now,
        observed_max=observed_max,
        observation_age_hours=observation_age_hours,
        heating_rate=heating_rate,
        remaining_model_rise=remaining_rise,
        future_radiation_max=future_radiation,
        resolved_lower_c=resolution[0] if resolution is not None else None,
        resolved_upper_c=resolution[1] if resolution is not None else None,
    )
    probabilities = condition_probability_range(
        unconditioned.probability_by_bucket,
        day_status.minimum_bucket,
        day_status.maximum_bucket,
    )
    if not d1_scored.empty:
        residual_errors = d1_scored.copy()
        residual_errors["residual_abs_error"] = (
            residual_errors.error
            - residual_errors.groupby("model").error.transform("mean")
        ).abs()
        residual_mae = residual_errors.groupby("model").residual_abs_error.mean()
        mae_map = residual_mae.to_dict()
    else:
        mae_map = {}
    available_mae = [
        float(mae_map[model]) * float(weight)
        for model, weight in zip(current.model, current.model_weight)
        if model in mae_map
    ]
    covered_weight = sum(
        float(weight)
        for model, weight in zip(current.model, current.model_weight)
        if model in mae_map
    )
    historical_mae = sum(available_mae) / covered_weight if covered_weight > 0 else None
    historical_days = int(d1_metrics.n.max()) if not d1_metrics.empty else 0
    history_score = (
        max(0.0, min(100.0, 100 - 35 * historical_mae))
        if historical_mae is not None
        else 50.0
    )
    spread_score = max(0.0, min(100.0, 105 - 25 * corrected.spread))
    sample_score = min(100.0, historical_days / 90 * 100)
    if day_status.is_locked:
        live_score = 100.0
    elif target != local_now.date():
        live_score = 70.0
    elif observation_age_hours is None:
        live_score = 35.0
    else:
        live_score = max(0.0, min(100.0, 110 - 30 * observation_age_hours))
    confidence_factors = {
        "historical_accuracy": history_score,
        "model_agreement": spread_score,
        "sample_size": sample_score,
        "live_data": live_score,
    }
    base_confidence = (
        0.40 * history_score
        + 0.30 * spread_score
        + 0.20 * sample_score
        + 0.10 * live_score
    )
    if taf_guidance is not None:
        confidence_factors["taf_guidance"] = float(taf_guidance.confidence_score)
        forecast_confidence = round(
            0.80 * base_confidence + 0.20 * taf_guidance.confidence_score
        )
    else:
        forecast_confidence = round(base_confidence)
    return LiveNowcast(
        current=current,
        corrected=corrected,
        heat=heat,
        day_status=day_status,
        probabilities=probabilities,
        observed_max=observed_max,
        heating_rate=heating_rate,
        expected_now=expected_now,
        cloud_cover=cloud_cover,
        wind_speed_kph=wind_speed,
        wind_direction_deg=wind_direction,
        wind_source=wind_source,
        temp_850_c=temp_850,
        radiation_wm2=radiation,
        remaining_rise_c=remaining_rise,
        future_radiation_max=future_radiation,
        forecast_confidence=int(max(0, min(100, forecast_confidence))),
        confidence_factors=confidence_factors,
        model_weights=dict(zip(current.model.astype(str), current.model_weight.astype(float))),
        taf_guidance=taf_guidance,
    )
