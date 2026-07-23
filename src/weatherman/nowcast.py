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
    metar_schedule_status,
    model_metrics,
    model_weight_map,
    resolved_market_range,
    score_frame,
    wind_heat_adjustment,
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
    raw_model_mean: float
    raw_model_spread: float
    weighted_raw_mean: float
    weighted_raw_spread: float
    bias_corrected_equal_mean: float
    bias_corrected_equal_spread: float
    stage_probabilities: dict[str, dict[int, float]]
    adjustment_contributions: dict[str, float]
    live_features: dict[str, float | None]
    metar_conditioned_probabilities: dict[int, float]
    metar_conditioned_mean: float
    metar_conditioned_spread: float
    final_forecast_mean: float
    final_forecast_spread: float
    taf_adjustment_c: float
    latest_observation_at: datetime | None
    expected_peak_at: datetime | None
    hours_to_peak: float | None
    metar_pending: bool
    metar_due_at: datetime | None


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
    float | None,
    float | None,
]:
    result = _hourly_for_target(frame, timezone_name, target, as_of)
    if result.empty:
        return None, None, None, None, None, None, None, None
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
    rates: list[float] = []
    for _, model_frame in result.groupby("model"):
        latest_run = model_frame.run_at.max()
        model_frame = model_frame[model_frame.run_at == latest_run].sort_values("valid_at")
        if len(model_frame) < 2:
            continue
        current_index = (model_frame.valid_at - reference_utc).abs().idxmin()
        current_time = pd.Timestamp(model_frame.loc[current_index, "valid_at"])
        prior = model_frame[
            (model_frame.valid_at < current_time)
            & (model_frame.valid_at >= current_time - timedelta(hours=2))
        ]
        if prior.empty:
            continue
        prior_row = prior.iloc[-1]
        elapsed = (current_time - pd.Timestamp(prior_row.valid_at)).total_seconds() / 3600
        if elapsed > 0:
            rates.append(
                (float(model_frame.loc[current_index, "temp_c"]) - float(prior_row.temp_c))
                / elapsed
            )

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
        median("dewpoint_c"),
        median("cloud_cover"),
        median("temp_850hpa_c"),
        median("radiation_wm2"),
        median("wind_kph"),
        circular_mean("wind_direction"),
        float(pd.Series(rates).median()) if rates else None,
    )


def remaining_heating_context(
    frame: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
    current_observed_temp: float | None = None,
    observed_max: float | None = None,
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
        if current_observed_temp is not None and observed_max is not None:
            # Anchor every future model path to the latest METAR before comparing
            # it with the maximum already observed. This prevents an evening model
            # path from keeping the heating window open merely because it rises
            # relative to its own (wrong) evening baseline.
            anchor = float(current_observed_temp) - expected_now
            anchored_peak = float((future.temp_c.astype(float) + anchor).max())
            rises.append(max(0.0, anchored_peak - float(observed_max)))
        else:
            rises.append(max(0.0, float(future.temp_c.max()) - expected_now))
        radiation_values = future.radiation_wm2.dropna()
        if not radiation_values.empty:
            future_radiation.append(float(radiation_values.max()))
    remaining_rise = max(rises) if rises else None
    radiation_max = max(future_radiation) if future_radiation else None
    return remaining_rise, radiation_max


def expected_peak_time(
    frame: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
) -> datetime | None:
    result = _hourly_for_target(frame, timezone_name, target, as_of)
    if result.empty:
        return None
    peak_timestamps: list[float] = []
    for _, model_frame in result.groupby("model"):
        latest_run = model_frame.run_at.max()
        model_frame = model_frame[model_frame.run_at == latest_run].sort_values("valid_at")
        if model_frame.empty or model_frame.temp_c.dropna().empty:
            continue
        peak_row = model_frame.loc[model_frame.temp_c.astype(float).idxmax()]
        peak_timestamps.append(pd.Timestamp(peak_row.valid_at).timestamp())
    if not peak_timestamps:
        return None
    epoch = float(pd.Series(peak_timestamps).median())
    return datetime.fromtimestamp(epoch, tz=ZoneInfo("UTC"))


def probability_moments(probabilities: dict[int, float]) -> tuple[float, float]:
    total = sum(probabilities.values())
    if total <= 0:
        raise ValueError("Probability distribution must contain positive mass")
    mean = sum(float(bucket) * probability for bucket, probability in probabilities.items()) / total
    variance = sum(
        probability * (float(bucket) - mean) ** 2
        for bucket, probability in probabilities.items()
    ) / total
    return float(mean), float(math.sqrt(max(0.0, variance)))


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


def recent_station_residual(scored: pd.DataFrame) -> float | None:
    """Recent error left after each model's longer-run bias, newest days weighted most."""
    if scored.empty:
        return None
    frame = scored.copy()
    frame["target_date"] = pd.to_datetime(frame.target_date).dt.date
    frame["model_bias"] = frame.groupby("model").error.transform("mean")
    # Positive means the station recently finished hotter than its bias-corrected
    # model values.
    frame["station_residual"] = -(frame.error - frame.model_bias)
    daily = (
        frame.groupby("target_date", as_index=False)
        .station_residual.median()
        .sort_values("target_date")
        .tail(7)
    )
    if daily.empty:
        return None
    weights = pd.Series([0.72 ** index for index in range(len(daily) - 1, -1, -1)])
    return float((daily.station_residual.reset_index(drop=True) * weights).sum() / weights.sum())


def _scaled_live_adjustments(contributions: dict[str, float]) -> dict[str, float]:
    raw_total = sum(contributions.values())
    clipped_total = max(-1.5, min(1.5, raw_total))
    if abs(raw_total) > 1e-9 and clipped_total != raw_total:
        scale = clipped_total / raw_total
        contributions = {name: value * scale for name, value in contributions.items()}
    return {**contributions, "total": clipped_total}


def observed_heating_rates(observations: pd.DataFrame) -> dict[str, float | None]:
    """Calculate comparable 30/60/120-minute station heating rates."""
    rates: dict[str, float | None] = {"30m": None, "60m": None, "120m": None}
    if len(observations) < 2:
        return rates
    frame = observations.sort_values("observed_at")
    latest = frame.iloc[-1]
    latest_at = pd.Timestamp(latest.observed_at)
    for minutes in (30, 60, 120):
        earlier = frame[frame.observed_at < latest_at]
        if earlier.empty:
            continue
        desired = latest_at - timedelta(minutes=minutes)
        index = (earlier.observed_at - desired).abs().idxmin()
        prior = earlier.loc[index]
        elapsed = (latest_at - pd.Timestamp(prior.observed_at)).total_seconds() / 3600
        # Do not label a five-minute comparison as a 60-minute rate.
        if elapsed < minutes / 60 * 0.5 or elapsed > minutes / 60 * 1.75:
            continue
        rates[f"{minutes}m"] = (float(latest.temp_c) - float(prior.temp_c)) / elapsed
    return rates


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
    routine_metar_minutes: list[int] | tuple[int, ...] | None = None,
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
    raw_equal = consensus(current.max_temp_c.tolist())
    weighted_raw = consensus(
        current.max_temp_c.tolist(),
        weights=current.model_weight.tolist(),
    )
    bias_equal = consensus(
        current.max_temp_c.tolist(),
        current.d1_bias.tolist(),
    )
    corrected = consensus(
        current.max_temp_c.tolist(),
        current.d1_bias.tolist(),
        weights=current.model_weight.tolist(),
    )
    wind_profile = wind_profile or {}

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
    heating_rates = observed_heating_rates(obs_today)
    comparable_rates = [
        value for value in heating_rates.values() if value is not None
    ]
    if comparable_rates:
        heating_rate = float(pd.Series(comparable_rates).median())

    observed_cooling = False
    if latest_obs is not None and observed_max is not None:
        observed_cooling = (
            float(latest_obs.temp_c) <= observed_max - 0.5
            or (heating_rate is not None and heating_rate <= 0.0)
        )
    taf_guidance = build_taf_guidance(
        tafs if tafs is not None else pd.DataFrame(),
        timezone_name=timezone_name,
        target=target,
        as_of=as_of,
        model_mean=corrected.mean,
        wind_profile=wind_profile,
        observed_cooling=observed_cooling,
    )

    (
        expected_now,
        expected_dewpoint,
        cloud_cover,
        temp_850,
        radiation,
        model_wind_speed,
        model_wind_direction,
        model_heating_rate,
    ) = hourly_context(hourly, timezone_name, target, as_of)
    current_observed_temp = float(latest_obs.temp_c) if latest_obs is not None else None
    remaining_rise, future_radiation = remaining_heating_context(
        hourly,
        timezone_name,
        target,
        as_of,
        current_observed_temp=current_observed_temp,
        observed_max=observed_max,
    )
    peak_at = expected_peak_time(hourly, timezone_name, target, as_of)
    hours_to_peak = (
        (peak_at - as_of_utc.to_pydatetime()).total_seconds() / 3600
        if peak_at is not None
        else None
    )
    observation_age_hours = None
    if latest_obs is not None:
        observation_age_hours = max(
            0.0,
            (as_of_utc - pd.Timestamp(latest_obs.observed_at)).total_seconds() / 3600,
        )
    latest_observation_at = (
        pd.Timestamp(latest_obs.observed_at).to_pydatetime()
        if latest_obs is not None
        else None
    )
    schedule = metar_schedule_status(
        as_of=as_of,
        latest_observation_at=latest_observation_at,
        routine_minutes=routine_metar_minutes,
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
    observed_dewpoint = (
        float(latest_obs.dewpoint_c)
        if latest_obs is not None and pd.notna(latest_obs.dewpoint_c)
        else None
    )
    observed_cloud = (
        float(latest_obs.cloud_cover)
        if latest_obs is not None
        and "cloud_cover" in latest_obs.index
        and pd.notna(latest_obs.cloud_cover)
        else None
    )
    heat = heat_spike_assessment(
        forecast_mean=corrected.mean,
        recent_baseline=recent_baseline,
        run_trend=trend,
        model_spread=corrected.spread,
        observed_temp=float(latest_obs.temp_c) if latest_obs is not None else None,
        observed_dewpoint=observed_dewpoint,
        expected_temp_now=expected_now if target == local_now.date() else None,
        heating_rate=heating_rate,
        cloud_cover=observed_cloud if observed_cloud is not None else cloud_cover,
        wind_speed_kph=wind_speed,
        wind_direction_deg=wind_direction,
        warm_wind_sectors=wind_profile.get("warm_sectors"),
        cool_wind_sectors=wind_profile.get("cool_sectors"),
        wind_source=wind_source,
        guidance_score_points=(
            taf_guidance.heat_score_points if taf_guidance is not None else 0
        ),
        guidance_adjustment_c=(
            0.0
        ),
        guidance_signals=(taf_guidance.signals if taf_guidance is not None else None),
    )
    taf_center_adjustment = (
        taf_guidance.center_adjustment_c if taf_guidance is not None else 0.0
    )
    taf_spread_addition = (
        taf_guidance.spread_addition_c if taf_guidance is not None else 0.0
    )
    live_observation_available = (
        target == local_now.date()
        and current_observed_temp is not None
        and observation_age_hours is not None
        and observation_age_hours <= 2
    )
    temperature_anomaly = (
        current_observed_temp - expected_now
        if live_observation_available and expected_now is not None
        else None
    )
    observed_dryness = (
        current_observed_temp - observed_dewpoint
        if live_observation_available and observed_dewpoint is not None
        else None
    )
    model_dryness = (
        expected_now - expected_dewpoint
        if expected_now is not None and expected_dewpoint is not None
        else None
    )
    dryness_surprise = (
        observed_dryness - model_dryness
        if observed_dryness is not None and model_dryness is not None
        else None
    )
    cloud_surprise = (
        cloud_cover - observed_cloud
        if live_observation_available
        and cloud_cover is not None
        and observed_cloud is not None
        else None
    )
    heating_surprise = (
        heating_rate - model_heating_rate
        if live_observation_available
        and heating_rate is not None
        and model_heating_rate is not None
        else None
    )
    station_residual = recent_station_residual(d1_scored)

    def limited(value: float | None, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value))) if value is not None else 0.0

    contributions = {
        "temperature_anchor": limited(
            0.45 * temperature_anomaly if temperature_anomaly is not None else None,
            -0.90,
            0.90,
        ),
        "dryness": limited(
            0.025 * dryness_surprise if dryness_surprise is not None else None,
            -0.20,
            0.20,
        ),
        "cloud": limited(
            0.003 * cloud_surprise if cloud_surprise is not None else None,
            -0.20,
            0.20,
        ),
        "heating_rate": limited(
            0.18 * heating_surprise if heating_surprise is not None else None,
            -0.30,
            0.30,
        ),
        "recent_station_error": limited(
            0.15 * station_residual
            if live_observation_available and station_residual is not None
            else None,
            -0.25,
            0.25,
        ),
        "radiation": limited(
            0.20 * (cloud_surprise / 100) * (radiation / 800)
            if cloud_surprise is not None and radiation is not None
            else None,
            -0.15,
            0.15,
        ),
        "wind": (
            wind_heat_adjustment(
                speed_kph=wind_speed,
                direction_deg=wind_direction,
                warm_sectors=wind_profile.get("warm_sectors"),
                cool_sectors=wind_profile.get("cool_sectors"),
                source=wind_source or "model",
            )
            if live_observation_available and wind_source == "METAR"
            else 0.0
        ),
        "run_trend": limited(
            0.15 * trend
            if live_observation_available and trend is not None
            else None,
            -0.20,
            0.20,
        ),
    }
    adjustments = _scaled_live_adjustments(contributions)
    live_adjustment = adjustments["total"]
    heat = HeatSpikeAssessment(
        heat.score,
        heat.status,
        live_adjustment,
        heat.signals,
    )
    signed = [value for name, value in adjustments.items() if name != "total" and abs(value) >= 0.05]
    contradictory = any(value > 0 for value in signed) and any(value < 0 for value in signed)
    live_sigma_floor = 0.80 if contradictory else 0.60 if len(signed) >= 4 else 0.65
    metar_unconditioned = consensus(
        (current.corrected_max + live_adjustment).tolist(),
        weights=current.model_weight.tolist(),
        sigma_floor=live_sigma_floor,
    )
    resolution = resolved_market_range(markets)
    day_status = assess_day_status(
        target_date=target,
        local_now=local_now,
        observed_max=observed_max,
        latest_observed_temp=current_observed_temp,
        observation_age_hours=observation_age_hours,
        heating_rate=heating_rate,
        remaining_model_rise=remaining_rise,
        future_radiation_max=future_radiation,
        resolved_lower_c=resolution[0] if resolution is not None else None,
        resolved_upper_c=resolution[1] if resolution is not None else None,
    )
    metar_probabilities = condition_probability_range(
        metar_unconditioned.probability_by_bucket,
        day_status.minimum_bucket,
        day_status.maximum_bucket,
    )
    final_unconditioned = consensus(
        (current.corrected_max + live_adjustment + taf_center_adjustment).tolist(),
        weights=current.model_weight.tolist(),
        sigma_floor=live_sigma_floor + taf_spread_addition,
    )
    probabilities = condition_probability_range(
        final_unconditioned.probability_by_bucket,
        day_status.minimum_bucket,
        day_status.maximum_bucket,
    )
    metar_mean, metar_spread = probability_moments(metar_probabilities)
    final_mean, final_spread = probability_moments(probabilities)
    stage_probabilities = {
        "Raw model mean": raw_equal.probability_by_bucket,
        "Weighted raw ensemble": weighted_raw.probability_by_bucket,
        "Bias corrected · equal weight": bias_equal.probability_by_bucket,
        "Bias corrected · performance weighted": corrected.probability_by_bucket,
        "METAR conditioned": metar_probabilities,
        "Final incl. TAF": probabilities,
    }
    live_features = {
        "temperature_anomaly_c": temperature_anomaly,
        "observed_dryness_c": observed_dryness,
        "model_dryness_c": model_dryness,
        "dryness_surprise_c": dryness_surprise,
        "observed_cloud_cover_pct": observed_cloud,
        "model_cloud_cover_pct": cloud_cover,
        "cloud_surprise_pct": cloud_surprise,
        "observed_heating_rate_cph": heating_rate,
        "observed_heating_rate_30m_cph": heating_rates["30m"],
        "observed_heating_rate_60m_cph": heating_rates["60m"],
        "observed_heating_rate_120m_cph": heating_rates["120m"],
        "model_heating_rate_cph": model_heating_rate,
        "heating_rate_surprise_cph": heating_surprise,
        "recent_station_residual_c": station_residual,
        "model_radiation_wm2": radiation,
        "future_radiation_max_wm2": future_radiation,
        "remaining_model_rise_c": remaining_rise,
    }
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
        raw_model_mean=raw_equal.mean,
        raw_model_spread=raw_equal.spread,
        weighted_raw_mean=weighted_raw.mean,
        weighted_raw_spread=weighted_raw.spread,
        bias_corrected_equal_mean=bias_equal.mean,
        bias_corrected_equal_spread=bias_equal.spread,
        stage_probabilities=stage_probabilities,
        adjustment_contributions=adjustments,
        live_features=live_features,
        metar_conditioned_probabilities=metar_probabilities,
        metar_conditioned_mean=metar_mean,
        metar_conditioned_spread=metar_spread,
        final_forecast_mean=final_mean,
        final_forecast_spread=final_spread,
        taf_adjustment_c=float(taf_center_adjustment),
        latest_observation_at=latest_observation_at,
        expected_peak_at=peak_at,
        hours_to_peak=hours_to_peak,
        metar_pending=schedule.is_pending,
        metar_due_at=schedule.due_at,
    )
