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
    model_freshness: pd.DataFrame
    forecast_data_stale: bool
    fresh_model_count: int
    stale_models: tuple[str, ...]
    latest_forecast_age_minutes: float | None
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
    live_features: dict[str, object]
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
    challenger_variants: dict[str, dict[str, object]]
    regime_memory: object | None = None


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
    result = result.sort_values("run_at").drop_duplicates(["model", "valid_at"], keep="last")
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
        future = model_frame[model_frame.valid_at >= reference_utc - timedelta(minutes=30)]
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
    variance = (
        sum(
            probability * (float(bucket) - mean) ** 2
            for bucket, probability in probabilities.items()
        )
        / total
    )
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
    weights = pd.Series([0.72**index for index in range(len(daily) - 1, -1, -1)])
    return float((daily.station_residual.reset_index(drop=True) * weights).sum() / weights.sum())


def rapid_heat_ramp_regime(
    actuals: pd.DataFrame,
    *,
    target: date,
    forecast_mean: float,
    profile: dict | None = None,
) -> dict[str, float | bool | None]:
    """Identify a fast warm-regime transition without adding a fixed temperature."""
    configured = profile or {}
    defaults: dict[str, float | bool | None] = {
        "active": False,
        "forecast_vs_latest_c": None,
        "latest_actual_change_c": None,
        "forecast_vs_two_back_c": None,
        "bias_multiplier": 1.0,
        "spread_multiplier": 1.0,
        "confidence_multiplier": 1.0,
    }
    if actuals.empty:
        return defaults
    frame = actuals.copy()
    frame["target_date"] = pd.to_datetime(frame.target_date).dt.date
    frame = (
        frame[frame.target_date < target]
        .sort_values("target_date")
        .drop_duplicates("target_date", keep="last")
        .tail(3)
    )
    if frame.empty:
        return defaults
    latest = frame.iloc[-1]
    if (target - latest.target_date).days > 2:
        return defaults
    forecast_vs_latest = float(forecast_mean) - float(latest.max_temp_c)
    previous_change = None
    forecast_vs_two_back = None
    if len(frame) >= 2:
        previous = frame.iloc[-2]
        previous_change = float(latest.max_temp_c) - float(previous.max_temp_c)
        forecast_vs_two_back = float(forecast_mean) - float(previous.max_temp_c)
    active = bool(
        forecast_vs_latest >= float(configured.get("one_day_threshold_c", 3.0))
        or (
            previous_change is not None
            and previous_change >= float(configured.get("prior_jump_threshold_c", 3.0))
            and forecast_vs_latest >= float(configured.get("continuation_threshold_c", 1.5))
        )
        or (
            forecast_vs_two_back is not None
            and forecast_vs_two_back >= float(configured.get("two_day_threshold_c", 5.0))
        )
    )
    if not active:
        return {
            **defaults,
            "forecast_vs_latest_c": forecast_vs_latest,
            "latest_actual_change_c": previous_change,
            "forecast_vs_two_back_c": forecast_vs_two_back,
        }
    return {
        "active": True,
        "forecast_vs_latest_c": forecast_vs_latest,
        "latest_actual_change_c": previous_change,
        "forecast_vs_two_back_c": forecast_vs_two_back,
        "bias_multiplier": max(
            0.0,
            min(1.0, float(configured.get("positive_bias_multiplier", 0.45))),
        ),
        "spread_multiplier": max(
            1.0,
            min(1.5, float(configured.get("spread_multiplier", 1.25))),
        ),
        "confidence_multiplier": max(
            0.5,
            min(1.0, float(configured.get("confidence_multiplier", 0.90))),
        ),
    }


def persistent_hot_regime(
    actuals: pd.DataFrame,
    scored: pd.DataFrame,
    *,
    target: date,
    forecast_mean: float,
    taf_guidance: TafGuidance | None,
    profile: dict | None = None,
) -> dict[str, float | bool | None]:
    """Detect continuation of established heat even when models no longer rise day-on-day."""
    configured = (profile or {}).get("persistent_hot") or {}
    defaults: dict[str, float | bool | None] = {
        "active": False,
        "latest_actual_c": None,
        "recent_baseline_c": None,
        "latest_anomaly_c": None,
        "forecast_vs_latest_c": None,
        "recent_warm_error_c": None,
        "taf_support": False,
        "clear_support": False,
        "bias_multiplier": 1.0,
        "spread_multiplier": 1.0,
        "confidence_multiplier": 1.0,
    }
    if not configured.get("enabled", False) or actuals.empty:
        return defaults
    frame = actuals.copy()
    frame["target_date"] = pd.to_datetime(frame.target_date).dt.date
    frame = (
        frame[frame.target_date < target]
        .sort_values("target_date")
        .drop_duplicates("target_date", keep="last")
        .tail(15)
    )
    if frame.empty:
        return defaults
    latest = frame.iloc[-1]
    if (target - latest.target_date).days > 2:
        return defaults
    latest_actual = float(latest.max_temp_c)
    baseline_values = frame.iloc[:-1].max_temp_c.astype(float).tail(14)
    recent_baseline = (
        float(baseline_values.median()) if not baseline_values.empty else latest_actual
    )
    anomaly = latest_actual - recent_baseline
    forecast_vs_latest = float(forecast_mean) - latest_actual

    recent_warm_error = None
    if not scored.empty:
        errors = scored.copy()
        errors["target_date"] = pd.to_datetime(errors.target_date).dt.date
        errors = errors[
            (errors.target_date < target)
            & (errors.target_date >= target - timedelta(days=5))
        ]
        if not errors.empty:
            # Forecast minus actual: a negative value means the station finished warmer.
            recent_warm_error = float(errors.groupby("target_date").error.median().tail(3).median())

    taf_support = bool(
        taf_guidance is not None
        and taf_guidance.temperature_influence_active
        and taf_guidance.max_temp_c is not None
        and taf_guidance.max_temp_c
        >= max(
            float(forecast_mean) + float(configured.get("minimum_taf_gap_c", 1.0)),
            latest_actual - float(configured.get("taf_below_latest_tolerance_c", 0.5)),
        )
    )
    clear_support = bool(
        taf_guidance is not None
        and taf_guidance.cloud_risk == "No significant cloud near peak"
        and not taf_guidance.precipitation_risk
        and not taf_guidance.thunderstorm_risk
    )
    hot_yesterday = bool(
        latest_actual >= float(configured.get("minimum_latest_actual_c", 37.0))
        or anomaly >= float(configured.get("minimum_latest_anomaly_c", 3.0))
    )
    forecast_still_hot = forecast_vs_latest >= -float(
        configured.get("maximum_forecast_drop_c", 2.5)
    )
    repeated_warm_error = bool(
        recent_warm_error is not None
        and recent_warm_error <= -float(configured.get("minimum_recent_warm_error_c", 0.6))
    )
    confirmations = sum(
        [
            bool(forecast_still_hot),
            bool(taf_support),
            bool(clear_support),
            bool(repeated_warm_error),
        ]
    )
    active = hot_yesterday and confirmations >= int(
        configured.get("minimum_confirmations", 2)
    )
    result = {
        **defaults,
        "active": active,
        "latest_actual_c": latest_actual,
        "recent_baseline_c": recent_baseline,
        "latest_anomaly_c": anomaly,
        "forecast_vs_latest_c": forecast_vs_latest,
        "recent_warm_error_c": recent_warm_error,
        "taf_support": taf_support,
        "clear_support": clear_support,
    }
    if not active:
        return result
    return {
        **result,
        "bias_multiplier": max(
            0.0,
            min(1.0, float(configured.get("positive_bias_multiplier", 0.20))),
        ),
        "spread_multiplier": max(
            1.0,
            min(1.6, float(configured.get("spread_multiplier", 1.30))),
        ),
        "confidence_multiplier": max(
            0.5,
            min(1.0, float(configured.get("confidence_multiplier", 0.88))),
        ),
    }


def regional_heat_cluster(
    current: pd.DataFrame,
    *,
    profile: dict | None,
    heat_regime_active: bool,
    persistent_hot_active: bool,
    taf_clear: bool,
) -> dict[str, float | bool | None | pd.Series]:
    """Protect a coherent warm regional-model cluster during an active heat regime."""
    defaults: dict[str, float | bool | None | pd.Series] = {
        "active": False,
        "regional_mean_c": None,
        "other_mean_c": None,
        "mean_gap_c": None,
        "multiplier": 1.0,
        "members": pd.Series(False, index=current.index),
    }
    if not profile or not profile.get("enabled", True) or current.empty or not heat_regime_active:
        return defaults
    persistent = profile.get("persistent_hot") or {}
    configured_models = {
        str(value)
        for value in (
            persistent.get("regional_models", [])
            if persistent_hot_active and persistent.get("regional_models")
            else profile.get("regional_models", [])
        )
    }
    if not configured_models:
        return defaults
    members = current.model.astype(str).isin(configured_models)
    if not members.any() or (~members).sum() == 0:
        return {**defaults, "members": members}
    regional_mean = float(current.loc[members, "corrected_max"].mean())
    other_mean = float(current.loc[~members, "corrected_max"].mean())
    gap = regional_mean - other_mean
    required_gap = float(profile.get("minimum_warm_gap_c", 0.6))
    if gap < required_gap:
        return {
            **defaults,
            "regional_mean_c": regional_mean,
            "other_mean_c": other_mean,
            "mean_gap_c": gap,
            "members": members,
        }
    multiplier = float(
        persistent.get("regional_weight_multiplier", 1.50)
        if persistent_hot_active
        else profile.get("regional_weight_multiplier", 1.35)
    )
    if not taf_clear:
        multiplier = min(multiplier, float(profile.get("unconfirmed_multiplier", 1.20)))
    return {
        "active": True,
        "regional_mean_c": regional_mean,
        "other_mean_c": other_mean,
        "mean_gap_c": gap,
        "multiplier": max(1.0, min(1.75, multiplier)),
        "members": members,
    }


def robust_outlier_multipliers(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Downweight isolated model maxima without deleting a plausible minority cluster."""
    numeric = values.astype(float)
    median = float(numeric.median())
    distances = (numeric - median).abs()
    mad = float(distances.median())
    robust_scale = max(0.50, 1.4826 * mad)
    soft_limit = max(1.25, 1.75 * robust_scale)
    multipliers = pd.Series(1.0, index=numeric.index, dtype=float)
    beyond = distances > soft_limit
    multipliers.loc[beyond] = (soft_limit / distances.loc[beyond].clip(lower=soft_limit)).clip(
        lower=0.25
    )
    # With only two models there is no majority from which to identify an outlier.
    if len(numeric) < 3:
        multipliers[:] = 1.0
    return multipliers, distances


def observation_path_residuals(
    hourly: pd.DataFrame,
    observations: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
) -> pd.DataFrame:
    """Compare recent METARs with the same latest model paths used by the nowcast."""
    if observations.empty:
        return pd.DataFrame(
            columns=["observed_at", "observed_temp_c", "expected_temp_c", "residual_c"]
        )
    paths = _hourly_for_target(hourly, timezone_name, target, as_of)
    if paths.empty:
        return pd.DataFrame(
            columns=["observed_at", "observed_temp_c", "expected_temp_c", "residual_c"]
        )
    paths = paths.sort_values("run_at").drop_duplicates(["model", "valid_at"], keep="last")
    latest_runs = paths.groupby("model").run_at.transform("max")
    paths = paths[paths.run_at == latest_runs]
    rows = []
    for observation in observations.sort_values("observed_at").tail(6).itertuples():
        observed_at = pd.Timestamp(observation.observed_at)
        expected_values: list[float] = []
        for _, model_frame in paths.groupby("model"):
            distance = (model_frame.valid_at - observed_at).abs()
            if distance.empty:
                continue
            nearest_index = distance.idxmin()
            if distance.loc[nearest_index] <= timedelta(minutes=75):
                expected_values.append(float(model_frame.loc[nearest_index, "temp_c"]))
        if not expected_values:
            continue
        expected = float(pd.Series(expected_values).median())
        observed = float(observation.temp_c)
        rows.append(
            {
                "observed_at": observed_at,
                "observed_temp_c": observed,
                "expected_temp_c": expected,
                "residual_c": observed - expected,
            }
        )
    return pd.DataFrame(rows)


def temperature_anchor_profile(
    residuals: pd.DataFrame,
    fallback_anomaly: float | None,
    hours_to_peak: float | None,
) -> tuple[float | None, float, int, float | None]:
    """Return effective path residual, adaptive gain, streak length and recent median."""
    if residuals.empty:
        effective = fallback_anomaly
        recent_median = fallback_anomaly
        streak = int(fallback_anomaly is not None and abs(fallback_anomaly) >= 0.30)
    else:
        recent = residuals.residual_c.astype(float).tail(3)
        latest = float(recent.iloc[-1])
        recent_median = float(recent.median())
        effective = 0.65 * latest + 0.35 * recent_median
        signs = recent[recent.abs() >= 0.30].map(lambda value: 1 if value > 0 else -1)
        streak = 0
        if not signs.empty:
            final_sign = int(signs.iloc[-1])
            for sign in reversed(signs.tolist()):
                if int(sign) != final_sign:
                    break
                streak += 1

    if hours_to_peak is None:
        gain = 0.45
    elif hours_to_peak > 4:
        gain = 0.50
    elif hours_to_peak > 2:
        gain = 0.60
    elif hours_to_peak > 0:
        gain = 0.72
    else:
        gain = 0.82
    if streak >= 3 and recent_median is not None and abs(recent_median) >= 0.40:
        gain = min(0.88, gain + 0.15)
    return effective, gain, streak, recent_median


def _direction_in_sectors(direction: float, sectors: object) -> bool:
    value = float(direction) % 360
    for sector in sectors or []:
        if not isinstance(sector, (list, tuple)) or len(sector) != 2:
            continue
        start, end = float(sector[0]) % 360, float(sector[1]) % 360
        if start <= end and start <= value <= end:
            return True
        if start > end and (value >= start or value <= end):
            return True
    return False


def _latest_hourly_paths(
    hourly: pd.DataFrame,
    timezone_name: str,
    target: date,
    as_of: datetime,
) -> pd.DataFrame:
    paths = _hourly_for_target(hourly, timezone_name, target, as_of)
    if paths.empty:
        return paths
    paths = paths.sort_values("run_at").drop_duplicates(["model", "valid_at"], keep="last")
    latest_runs = paths.groupby("model").run_at.transform("max")
    return paths[paths.run_at == latest_runs].copy()


def _path_expected_temperature(
    paths: pd.DataFrame,
    timestamp: pd.Timestamp,
    *,
    maximum_distance_minutes: float = 50,
) -> float | None:
    values: list[float] = []
    for _, model_frame in paths.groupby("model"):
        distance = (model_frame.valid_at - timestamp).abs()
        if distance.empty:
            continue
        nearest = distance.idxmin()
        if distance.loc[nearest] <= timedelta(minutes=maximum_distance_minutes):
            values.append(float(model_frame.loc[nearest, "temp_c"]))
    return float(pd.Series(values).median()) if values else None


def phase_vs_amplitude_regime(
    hourly: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    timezone_name: str,
    target: date,
    as_of: datetime,
    hours_to_peak: float | None,
    profile: dict | None,
) -> dict[str, float | bool | None | str]:
    """Separate an early/late model curve from a persistent vertical level error."""
    configured = profile or {}
    defaults: dict[str, float | bool | None | str] = {
        "active": False,
        "classification": "insufficient data",
        "phase_shift_hours": 0.0,
        "same_time_residual_c": None,
        "level_residual_after_shift_c": None,
        "baseline_rmse_c": None,
        "phase_rmse_c": None,
        "anchor_blend": 0.0,
    }
    if not configured.get("enabled", False) or len(observations) < 3:
        return defaults
    if hours_to_peak is not None and hours_to_peak <= float(
        configured.get("minimum_hours_to_peak", 1.0)
    ):
        return {**defaults, "classification": "near peak · level retained"}
    paths = _latest_hourly_paths(hourly, timezone_name, target, as_of)
    if paths.empty:
        return defaults
    frame = observations.sort_values("observed_at").copy()
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    frame = frame[
        frame.observed_at
        >= latest_at - timedelta(hours=float(configured.get("window_hours", 3.5)))
    ].tail(7)
    if len(frame) < int(configured.get("minimum_reports", 3)):
        return defaults

    def residuals_for_shift(shift_hours: float) -> list[float]:
        values: list[float] = []
        for observation in frame.itertuples():
            expected = _path_expected_temperature(
                paths,
                pd.Timestamp(observation.observed_at) + timedelta(hours=shift_hours),
            )
            if expected is not None:
                values.append(float(observation.temp_c) - expected)
        return values

    same_time = residuals_for_shift(0.0)
    minimum_reports = int(configured.get("minimum_reports", 3))
    if len(same_time) < minimum_reports:
        return defaults

    def rmse(values: list[float]) -> float:
        return math.sqrt(sum(value * value for value in values) / len(values))

    baseline_rmse = rmse(same_time)
    same_time_residual = float(pd.Series(same_time).median())
    maximum_shift = float(configured.get("maximum_phase_shift_hours", 3.0))
    step = max(0.25, float(configured.get("phase_step_hours", 0.5)))
    shift_count = int(round(maximum_shift / step))
    candidates: list[tuple[float, float, list[float]]] = []
    for index in range(-shift_count, shift_count + 1):
        shift = index * step
        shifted_residuals = residuals_for_shift(shift)
        if len(shifted_residuals) >= minimum_reports:
            candidates.append((rmse(shifted_residuals), shift, shifted_residuals))
    if not candidates:
        return defaults
    best_rmse, best_shift, best_residuals = min(
        candidates,
        key=lambda item: (item[0], abs(item[1])),
    )
    level_after_shift = float(pd.Series(best_residuals).median())
    minimum_shift = float(configured.get("minimum_phase_shift_hours", 0.75))
    minimum_gain = float(configured.get("minimum_rmse_gain_c", 0.30))
    maximum_phase_rmse = float(configured.get("maximum_phase_rmse_c", 1.0))
    active = bool(
        abs(best_shift) >= minimum_shift
        and baseline_rmse - best_rmse >= minimum_gain
        and best_rmse <= maximum_phase_rmse
    )
    if not active:
        return {
            **defaults,
            "classification": "level/amplitude",
            "same_time_residual_c": same_time_residual,
            "level_residual_after_shift_c": level_after_shift,
            "baseline_rmse_c": baseline_rmse,
            "phase_rmse_c": best_rmse,
        }
    return {
        "active": True,
        "classification": "phase-dominant",
        "phase_shift_hours": float(best_shift),
        "same_time_residual_c": same_time_residual,
        "level_residual_after_shift_c": level_after_shift,
        "baseline_rmse_c": baseline_rmse,
        "phase_rmse_c": best_rmse,
        "anchor_blend": max(
            0.0,
            min(0.90, float(configured.get("phase_anchor_blend", 0.75))),
        ),
    }


def _recent_temperature_rate(frame: pd.DataFrame) -> float | None:
    if len(frame) < 2:
        return None
    elapsed = (
        pd.Timestamp(frame.observed_at.iloc[-1]) - pd.Timestamp(frame.observed_at.iloc[0])
    ).total_seconds() / 3600
    if elapsed <= 0:
        return None
    return (float(frame.temp_c.iloc[-1]) - float(frame.temp_c.iloc[0])) / elapsed


def maritime_advection_regime(
    observations: pd.DataFrame,
    *,
    profile: dict | None,
) -> dict[str, float | bool | None]:
    """Detect an early North-Sea-type cooling intrusion from observed wind changes."""
    configured = profile or {}
    defaults: dict[str, float | bool | None] = {
        "active": False,
        "temperature_rate_cph": None,
        "wind_speed_kph": None,
        "wind_speed_change_kph": None,
        "maritime_fraction": None,
        "entered_maritime_sector": False,
        "center_adjustment_c": 0.0,
        "positive_factor_multiplier": 1.0,
        "remaining_rise_cap_c": None,
        "confidence_multiplier": 1.0,
    }
    minimum_reports = int(configured.get("minimum_reports", 3))
    if not configured.get("enabled", False) or len(observations) < minimum_reports:
        return defaults
    frame = observations.sort_values("observed_at").copy()
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    frame = frame[
        frame.observed_at
        >= latest_at - timedelta(hours=float(configured.get("window_hours", 3.0)))
    ]
    usable = frame.dropna(subset=["wind_kph", "wind_direction"])
    if len(usable) < minimum_reports:
        return defaults
    in_sector = usable.wind_direction.astype(float).map(
        lambda value: _direction_in_sectors(value, configured.get("maritime_sectors"))
    )
    recent_fraction = float(in_sector.tail(minimum_reports).mean())
    latest_speed = float(usable.wind_kph.iloc[-1])
    speed_change = latest_speed - float(usable.wind_kph.iloc[0])
    rate = _recent_temperature_rate(frame)
    entered_sector = bool(not in_sector.iloc[0] and in_sector.iloc[-1])
    plateau = rate is not None and rate <= float(
        configured.get("maximum_temperature_rate_cph", 0.20)
    )
    enough_wind = latest_speed >= float(configured.get("minimum_wind_kph", 14.0))
    strengthened = speed_change >= float(configured.get("minimum_wind_increase_kph", 2.0))
    strong = latest_speed >= float(configured.get("strong_wind_kph", 18.0))
    active = bool(
        recent_fraction >= float(configured.get("minimum_maritime_fraction", 2 / 3))
        and plateau
        and enough_wind
        and (entered_sector or strengthened or strong)
    )
    result = {
        **defaults,
        "active": active,
        "temperature_rate_cph": rate,
        "wind_speed_kph": latest_speed,
        "wind_speed_change_kph": speed_change,
        "maritime_fraction": recent_fraction,
        "entered_maritime_sector": entered_sector,
    }
    if not active:
        return result
    cooling_strength = max(0.0, -(rate or 0.0))
    adjustment = min(
        float(configured.get("maximum_cooling_adjustment_c", 0.65)),
        float(configured.get("base_cooling_adjustment_c", 0.30))
        + 0.15 * cooling_strength
        + 0.015 * max(0.0, latest_speed - float(configured.get("minimum_wind_kph", 14.0))),
    )
    return {
        **result,
        "center_adjustment_c": -adjustment,
        "positive_factor_multiplier": max(
            0.0,
            min(1.0, float(configured.get("positive_factor_multiplier", 0.25))),
        ),
        "remaining_rise_cap_c": max(
            0.0,
            float(configured.get("remaining_rise_cap_c", 0.40)),
        ),
        "confidence_multiplier": max(
            0.5,
            min(1.0, float(configured.get("confidence_multiplier", 0.90))),
        ),
    }


def maritime_low_range_regime(
    observations: pd.DataFrame,
    *,
    local_now: datetime,
    profile: dict | None,
) -> dict[str, float | bool | None]:
    """Detect a stable strong sea-wind day whose daily temperature range is capped."""
    configured = profile or {}
    defaults: dict[str, float | bool | None] = {
        "active": False,
        "temperature_rate_cph": None,
        "recent_range_c": None,
        "daily_range_c": None,
        "median_wind_kph": None,
        "sea_wind_fraction": None,
        "positive_factor_multiplier": 1.0,
        "spread_multiplier": 1.0,
        "remaining_rise_cap_c": None,
        "confidence_multiplier": 1.0,
    }
    minimum_reports = int(configured.get("minimum_reports", 4))
    if (
        not configured.get("enabled", False)
        or len(observations) < minimum_reports
        or local_now.hour < int(configured.get("minimum_local_hour", 10))
    ):
        return defaults
    frame = observations.sort_values("observed_at").copy()
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    recent = frame[
        frame.observed_at
        >= latest_at - timedelta(hours=float(configured.get("window_hours", 4.0)))
    ]
    usable = recent.dropna(subset=["wind_kph", "wind_direction"])
    if len(usable) < minimum_reports:
        return defaults
    sea_wind = usable.wind_direction.astype(float).map(
        lambda value: _direction_in_sectors(value, configured.get("sea_wind_sectors"))
    )
    fraction = float(sea_wind.mean())
    median_wind = float(usable.wind_kph.astype(float).median())
    recent_range = float(recent.temp_c.max() - recent.temp_c.min())
    daily_range = float(frame.temp_c.max() - frame.temp_c.min())
    rate = _recent_temperature_rate(recent)
    active = bool(
        fraction >= float(configured.get("minimum_sea_wind_fraction", 0.80))
        and median_wind >= float(configured.get("minimum_wind_kph", 28.0))
        and recent_range <= float(configured.get("maximum_recent_range_c", 1.5))
        and daily_range <= float(configured.get("maximum_daily_range_c", 4.5))
        and rate is not None
        and abs(rate) <= float(configured.get("maximum_abs_temperature_rate_cph", 0.30))
    )
    result = {
        **defaults,
        "active": active,
        "temperature_rate_cph": rate,
        "recent_range_c": recent_range,
        "daily_range_c": daily_range,
        "median_wind_kph": median_wind,
        "sea_wind_fraction": fraction,
    }
    if not active:
        return result
    return {
        **result,
        "positive_factor_multiplier": max(
            0.0,
            min(1.0, float(configured.get("positive_factor_multiplier", 0.15))),
        ),
        "spread_multiplier": max(
            0.70,
            min(1.0, float(configured.get("spread_multiplier", 0.85))),
        ),
        "remaining_rise_cap_c": max(
            0.0,
            float(configured.get("remaining_rise_cap_c", 0.40)),
        ),
        "confidence_multiplier": max(
            0.5,
            min(1.0, float(configured.get("confidence_multiplier", 0.95))),
        ),
    }


def _damp_positive_contributions(
    contributions: dict[str, float],
    multiplier: float,
) -> dict[str, float]:
    bounded = max(0.0, min(1.0, float(multiplier)))
    return {
        name: value * bounded if value > 0 else value
        for name, value in contributions.items()
    }


def dewpoint_trend(observations: pd.DataFrame) -> float | None:
    """Observed dewpoint change per hour over the latest usable two-hour window."""
    if observations.empty or "dewpoint_c" not in observations:
        return None
    frame = observations.dropna(subset=["dewpoint_c"]).sort_values("observed_at")
    if len(frame) < 2:
        return None
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    recent = frame[frame.observed_at >= latest_at - timedelta(hours=2)]
    if len(recent) < 2:
        return None
    elapsed = (
        pd.Timestamp(recent.observed_at.iloc[-1]) - pd.Timestamp(recent.observed_at.iloc[0])
    ).total_seconds() / 3600
    if elapsed <= 0:
        return None
    return float((recent.dewpoint_c.iloc[-1] - recent.dewpoint_c.iloc[0]) / elapsed)


def hours_until_critical_window_end(
    local_now: datetime,
    critical_window_local: list[str] | tuple[str, ...] | None,
) -> float | None:
    """Return time until the configured end of useful airport heating."""
    if not critical_window_local or len(critical_window_local) != 2:
        return None
    try:
        end_hour, end_minute = (
            int(value)
            for value in str(critical_window_local[1]).split(":", maxsplit=1)
        )
    except (TypeError, ValueError):
        return None
    end = local_now.replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0,
    )
    return (end - local_now).total_seconds() / 3600


def post_convective_uncertainty(
    observations: pd.DataFrame,
    as_of: datetime,
    profile: dict | None,
) -> dict[str, float | bool | None]:
    """Detect recent observed convection without imposing a directional bias."""
    defaults: dict[str, float | bool | None] = {
        "active": False,
        "reports": 0.0,
        "hours_since_latest": None,
        "spread_multiplier": 1.0,
        "confidence_multiplier": 1.0,
    }
    if not profile or not profile.get("enabled") or observations.empty:
        return defaults
    if "raw" not in observations or "observed_at" not in observations:
        return defaults
    frame = observations.dropna(subset=["observed_at"]).copy()
    frame["observed_at"] = pd.to_datetime(frame.observed_at, utc=True)
    as_of_utc = pd.Timestamp(as_of).tz_convert("UTC")
    window_hours = max(1.0, float(profile.get("window_hours", 48)))
    frame = frame[
        (frame.observed_at <= as_of_utc)
        & (frame.observed_at >= as_of_utc - timedelta(hours=window_hours))
    ]
    if frame.empty:
        return defaults
    raw = frame.raw.fillna("").astype(str).str.upper()
    convective = raw.str.contains(
        r"(?<![A-Z])(?:VCTS|TS[A-Z]*|CB)(?![A-Z])",
        regex=True,
    )
    reports = int(convective.sum())
    minimum_reports = max(1, int(profile.get("minimum_reports", 2)))
    if reports < minimum_reports:
        return {**defaults, "reports": float(reports)}
    latest = pd.Timestamp(frame.loc[convective, "observed_at"].max())
    hours_since_latest = max(0.0, (as_of_utc - latest).total_seconds() / 3600)
    return {
        "active": True,
        "reports": float(reports),
        "hours_since_latest": hours_since_latest,
        "spread_multiplier": max(
            1.0,
            min(1.5, float(profile.get("spread_multiplier", 1.5))),
        ),
        "confidence_multiplier": max(
            0.5,
            min(1.0, float(profile.get("confidence_multiplier", 0.85))),
        ),
    }


def late_dry_mixing_adjustment(
    observations: pd.DataFrame,
    *,
    corrected_model_mean: float,
    local_now: datetime,
    hours_to_window_end: float | None,
    wind_speed_kph: float | None,
) -> tuple[float, str | None, bool]:
    """Detect a clear, weak-wind late heating tail with rapid drying."""
    if (
        observations.empty
        or hours_to_window_end is None
        or hours_to_window_end < 1.5
        or local_now.hour < 12
    ):
        return 0.0, None, False
    frame = observations.sort_values("observed_at")
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    observation_age_hours = (
        pd.Timestamp(local_now).tz_convert("UTC") - latest_at
    ).total_seconds() / 3600
    if observation_age_hours < 0 or observation_age_hours > 1.5:
        return 0.0, None, False
    recent = frame[frame.observed_at >= latest_at - timedelta(hours=2)]
    if len(recent) < 2:
        return 0.0, None, False
    elapsed = (
        pd.Timestamp(recent.observed_at.iloc[-1])
        - pd.Timestamp(recent.observed_at.iloc[0])
    ).total_seconds() / 3600
    if elapsed <= 0:
        return 0.0, None, False
    temperature_trend = (
        float(recent.temp_c.iloc[-1]) - float(recent.temp_c.iloc[0])
    ) / elapsed
    drying_rate = dewpoint_trend(recent)
    observed_max = float(frame.temp_c.max())
    model_ceiling_reached_early = (
        hours_to_window_end >= 2.0
        and observed_max >= float(corrected_model_mean) - 0.5
    )
    raw = recent.raw.fillna("").astype(str).str.upper() if "raw" in recent else None
    cavok = bool(raw.str.contains(r"\bCAVOK\b", regex=True).all()) if raw is not None else False
    cloud_values = (
        recent.cloud_cover.dropna().astype(float)
        if "cloud_cover" in recent
        else pd.Series(dtype=float)
    )
    clear = cavok or (
        not cloud_values.empty and float(cloud_values.median()) <= 25.0
    )
    weak_wind = wind_speed_kph is not None and wind_speed_kph <= 18.0
    active = (
        model_ceiling_reached_early
        and drying_rate is not None
        and drying_rate <= -0.5
        and temperature_trend >= -0.1
        and clear
        and weak_wind
    )
    if not active:
        return 0.0, None, model_ceiling_reached_early
    return (
        0.30,
        "Late dry mixing: the model ceiling is already reached while clear, "
        "weak-wind observations keep drying without cooling",
        model_ceiling_reached_early,
    )


def failed_convection_adjustment(
    observations: pd.DataFrame,
    taf_guidance: TafGuidance | None,
    local_now: datetime,
    hours_to_peak: float | None,
) -> tuple[float, str | None]:
    """Recover cautiously when forecast peak-window convection is not materialising."""
    if taf_guidance is None or observations.empty or local_now.hour < 11:
        return 0.0, None
    risk = (
        taf_guidance.thunderstorm_risk
        or taf_guidance.precipitation_risk
        or taf_guidance.cloud_risk == "BKN/OVC near peak"
    )
    if not risk or (hours_to_peak is not None and hours_to_peak > 5):
        return 0.0, None
    frame = observations.sort_values("observed_at")
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    recent = frame[frame.observed_at >= latest_at - timedelta(hours=2)]
    if len(recent) < 2:
        return 0.0, None
    raw = " ".join(recent.raw.fillna("").astype(str)).upper() if "raw" in recent else ""
    weather_tokens = (" TS", "TS", "RA", "SH", "DZ", "SN", "GR", "CB")
    if any(token in raw for token in weather_tokens):
        return 0.0, None
    cloud_values = (
        recent.cloud_cover.dropna().astype(float)
        if "cloud_cover" in recent
        else pd.Series(dtype=float)
    )
    if not cloud_values.empty and float(cloud_values.median()) > 55:
        return 0.0, None
    if taf_guidance.thunderstorm_risk:
        adjustment = 0.35
        label = "TAF thunderstorm/CB risk has not materialised in recent METARs"
    elif taf_guidance.precipitation_risk:
        adjustment = 0.25
        label = "TAF precipitation risk has not materialised in recent METARs"
    else:
        adjustment = 0.15
        label = "Forecast BKN/OVC has not materialised in recent METARs"
    return adjustment, label


def clear_sky_override_adjustment(
    observations: pd.DataFrame,
    *,
    model_cloud_cover: float | None,
    taf_guidance: TafGuidance | None,
) -> tuple[float, str | None]:
    """Counter a model cloud brake only after repeated clear station reports."""
    if observations.empty or model_cloud_cover is None or model_cloud_cover < 35:
        return 0.0, None
    frame = observations.sort_values("observed_at")
    latest_at = pd.Timestamp(frame.observed_at.iloc[-1])
    recent = frame[frame.observed_at >= latest_at - timedelta(hours=1.5)].tail(4)
    if len(recent) < 2:
        return 0.0, None
    raw = recent.raw.fillna("").astype(str).str.upper() if "raw" in recent else None
    cavok_fraction = (
        float(raw.str.contains(r"\bCAVOK\b", regex=True).mean())
        if raw is not None
        else 0.0
    )
    observed_cloud = (
        recent.cloud_cover.dropna().astype(float)
        if "cloud_cover" in recent
        else pd.Series(dtype=float)
    )
    station_clear = cavok_fraction >= 0.5 or (
        not observed_cloud.empty and float(observed_cloud.median()) <= 20
    )
    if not station_clear:
        return 0.0, None
    observed_median = float(observed_cloud.median()) if not observed_cloud.empty else 0.0
    cloud_gap = max(0.0, float(model_cloud_cover) - observed_median)
    adjustment = min(0.30, 0.006 * cloud_gap)
    taf_clear = bool(
        taf_guidance is not None
        and taf_guidance.cloud_risk == "No significant cloud near peak"
        and not taf_guidance.precipitation_risk
        and not taf_guidance.thunderstorm_risk
    )
    if taf_clear:
        adjustment = min(0.40, adjustment + 0.10)
    return (
        adjustment,
        "Clear-sky override: repeated clear METARs contradict the model cloud brake"
        + (" and the TAF confirms a clear peak window" if taf_clear else ""),
    )


def _protect_persistent_anchor(
    contributions: dict[str, float],
    *,
    anchor_streak: int,
) -> dict[str, float]:
    """Prevent weak opposing factors from erasing a confirmed three-METAR anchor."""
    anchor = float(contributions.get("temperature_anchor", 0.0))
    if anchor_streak < 3 or abs(anchor) < 0.35:
        return contributions
    direction = 1.0 if anchor > 0 else -1.0
    supporting = sum(abs(value) for value in contributions.values() if value * direction > 0)
    opposing_names = [name for name, value in contributions.items() if value * direction < 0]
    opposition = sum(abs(contributions[name]) for name in opposing_names)
    minimum_net = abs(anchor) * 0.35
    if supporting - opposition >= minimum_net or opposition <= 0:
        return contributions
    allowed_opposition = max(0.0, supporting - minimum_net)
    scale = allowed_opposition / opposition
    return {
        name: value * scale if name in opposing_names else value
        for name, value in contributions.items()
    }


def _scaled_live_adjustments(contributions: dict[str, float]) -> dict[str, float]:
    raw_total = sum(contributions.values())
    clipped_total = max(-2.0, min(2.0, raw_total))
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
    critical_window_local: list[str] | tuple[str, ...] | None = None,
    post_convective_profile: dict | None = None,
    heat_regime_profile: dict | None = None,
    phase_amplitude_profile: dict | None = None,
    maritime_advection_profile: dict | None = None,
    maritime_low_range_profile: dict | None = None,
    maximum_model_age_minutes: int = 90,
    _disabled_factors: frozenset[str] = frozenset(),
    _build_challengers: bool = True,
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
    fetched = (
        pd.to_datetime(current.fetched_at, utc=True, errors="coerce")
        if "fetched_at" in current
        else pd.Series(pd.NaT, index=current.index, dtype="datetime64[ns, UTC]")
    )
    fetched = fetched.fillna(pd.to_datetime(current.run_at, utc=True, errors="coerce"))
    current["data_timestamp"] = fetched
    current["age_minutes"] = (
        (as_of_utc - current.data_timestamp).dt.total_seconds() / 60
    ).clip(lower=0)
    freshness_limit = max(1, int(maximum_model_age_minutes))
    current["is_fresh"] = current.age_minutes <= freshness_limit
    fresh_current = current[current.is_fresh].copy()
    forecast_data_stale = len(fresh_current) < 2
    if not forecast_data_stale:
        selected_models = set(fresh_current.model.astype(str))
        current["used_in_forecast"] = current.model.astype(str).isin(selected_models)
        forecast_current = fresh_current
    else:
        current["used_in_forecast"] = True
        forecast_current = current.copy()
    model_freshness = current.copy()
    stale_models = tuple(
        model_freshness.loc[~model_freshness.is_fresh, "model"].astype(str).tolist()
    )
    fresh_model_count = int(model_freshness.is_fresh.sum())
    latest_forecast_age_minutes = (
        float(model_freshness.age_minutes.min())
        if model_freshness.age_minutes.notna().any()
        else None
    )
    current = forecast_current

    d1 = available[available.horizon == "D-1"].copy()
    if not d1.empty:
        d1 = d1[pd.to_datetime(d1.target_date).dt.date < target]
    prior_actuals = actuals.copy()
    if not prior_actuals.empty:
        prior_actuals = prior_actuals[pd.to_datetime(prior_actuals.target_date).dt.date < target]
    d1_scored = score_frame(d1, prior_actuals)
    if not d1_scored.empty:
        d1_scored["target_date"] = pd.to_datetime(d1_scored.target_date).dt.date
        d1_scored = d1_scored[d1_scored.target_date >= target - timedelta(days=90)]
    d1_metrics = model_metrics(d1_scored)
    bias_map = dict(zip(d1_metrics.model, d1_metrics.bias)) if not d1_metrics.empty else {}
    weight_map = model_weight_map(d1_scored)
    fallback_weight = float(pd.Series(weight_map.values()).median()) if weight_map else 1.0
    raw_equal = consensus(current.max_temp_c.tolist())
    wind_profile = wind_profile or {}
    preliminary_taf = build_taf_guidance(
        tafs if tafs is not None else pd.DataFrame(),
        timezone_name=timezone_name,
        target=target,
        as_of=as_of,
        model_mean=raw_equal.mean,
        wind_profile=wind_profile,
        observed_cooling=False,
    )
    rapid_heat = rapid_heat_ramp_regime(
        prior_actuals if "rapid_heat_ramp" not in _disabled_factors else pd.DataFrame(),
        target=target,
        forecast_mean=raw_equal.mean,
        profile=heat_regime_profile,
    )
    persistent_hot = persistent_hot_regime(
        (
            prior_actuals
            if "persistent_hot" not in _disabled_factors
            else pd.DataFrame()
        ),
        d1_scored,
        target=target,
        forecast_mean=raw_equal.mean,
        taf_guidance=preliminary_taf,
        profile=heat_regime_profile,
    )
    current["historical_d1_bias"] = current.model.map(bias_map).fillna(0).astype(float)
    current["d1_bias"] = current.historical_d1_bias
    active_bias_multipliers = [
        float(regime["bias_multiplier"])
        for regime in (rapid_heat, persistent_hot)
        if regime["active"]
    ]
    effective_bias_multiplier = (
        min(active_bias_multipliers) if active_bias_multipliers else 1.0
    )
    if effective_bias_multiplier < 1.0:
        positive_bias = current.d1_bias > 0
        current.loc[positive_bias, "d1_bias"] = (
            current.loc[positive_bias, "d1_bias"]
            * effective_bias_multiplier
        )
    current["corrected_max"] = current.max_temp_c - current.d1_bias
    current["performance_weight"] = (
        current.model.map(weight_map).fillna(fallback_weight).astype(float)
    )
    outlier_multipliers, robust_distances = robust_outlier_multipliers(current.corrected_max)
    current["outlier_multiplier"] = outlier_multipliers
    current["robust_distance_c"] = robust_distances
    taf_clear = bool(
        preliminary_taf is not None
        and preliminary_taf.cloud_risk == "No significant cloud near peak"
        and not preliminary_taf.precipitation_risk
        and not preliminary_taf.thunderstorm_risk
    )
    cluster = regional_heat_cluster(
        current,
        profile=(
            heat_regime_profile
            if "regional_cluster" not in _disabled_factors
            else None
        ),
        heat_regime_active=bool(rapid_heat["active"] or persistent_hot["active"]),
        persistent_hot_active=bool(persistent_hot["active"]),
        taf_clear=taf_clear,
    )
    if cluster["active"]:
        members = cluster["members"]
        assert isinstance(members, pd.Series)
        current.loc[members, "outlier_multiplier"] = current.loc[
            members, "outlier_multiplier"
        ].clip(lower=0.75)
    current["base_model_weight"] = current.performance_weight * current.outlier_multiplier
    current["base_model_weight"] = (
        current.base_model_weight / current.base_model_weight.sum()
    )
    full_bias_baseline = consensus(
        current.max_temp_c.tolist(),
        current.historical_d1_bias.tolist(),
        weights=current.base_model_weight.tolist(),
    )
    bias_relaxed_baseline = consensus(
        current.max_temp_c.tolist(),
        current.d1_bias.tolist(),
        weights=current.base_model_weight.tolist(),
    )
    current["regime_weight_multiplier"] = 1.0
    if cluster["active"]:
        members = cluster["members"]
        assert isinstance(members, pd.Series)
        current.loc[members, "regime_weight_multiplier"] = float(cluster["multiplier"])
    current["model_weight"] = (
        current.base_model_weight * current.regime_weight_multiplier
    )
    current["model_weight"] = current.model_weight / current.model_weight.sum()
    weighted_raw = consensus(
        current.max_temp_c.tolist(),
        weights=current.model_weight.tolist(),
    )
    bias_equal = consensus(
        current.max_temp_c.tolist(),
        current.d1_bias.tolist(),
    )
    corrected_unbroadened = consensus(
        current.max_temp_c.tolist(),
        current.d1_bias.tolist(),
        weights=current.model_weight.tolist(),
    )
    active_spread_multipliers = [
        float(regime["spread_multiplier"])
        for regime in (rapid_heat, persistent_hot)
        if regime["active"]
    ]
    heat_spread_multiplier = (
        max(active_spread_multipliers) if active_spread_multipliers else 1.0
    )
    corrected = (
        consensus(
            current.max_temp_c.tolist(),
            current.d1_bias.tolist(),
            weights=current.model_weight.tolist(),
            sigma_floor=(
                corrected_unbroadened.spread
                * heat_spread_multiplier
            ),
        )
        if heat_spread_multiplier > 1.0
        else corrected_unbroadened
    )
    rapid_heat_adjustment = (
        bias_relaxed_baseline.mean - full_bias_baseline.mean
        if rapid_heat["active"]
        else 0.0
    )
    persistent_hot_adjustment = (
        bias_relaxed_baseline.mean - full_bias_baseline.mean
        if persistent_hot["active"]
        else 0.0
    )
    regional_cluster_adjustment = corrected.mean - bias_relaxed_baseline.mean

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
            heating_rate = float((recent_obs.temp_c.iloc[-1] - recent_obs.temp_c.iloc[0]) / elapsed)
    heating_rates = observed_heating_rates(obs_today)
    comparable_rates = [value for value in heating_rates.values() if value is not None]
    if comparable_rates:
        heating_rate = float(pd.Series(comparable_rates).median())

    observed_cooling = False
    if latest_obs is not None and observed_max is not None:
        observed_cooling = float(latest_obs.temp_c) <= observed_max - 0.5 or (
            heating_rate is not None and heating_rate <= 0.0
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
        pd.Timestamp(latest_obs.observed_at).to_pydatetime() if latest_obs is not None else None
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
    hours_to_window_end = hours_until_critical_window_end(
        local_now,
        critical_window_local,
    )
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
        guidance_score_points=(taf_guidance.heat_score_points if taf_guidance is not None else 0),
        guidance_adjustment_c=(0.0),
        guidance_signals=(taf_guidance.signals if taf_guidance is not None else None),
    )
    taf_center_adjustment = taf_guidance.center_adjustment_c if taf_guidance is not None else 0.0
    taf_spread_addition = taf_guidance.spread_addition_c if taf_guidance is not None else 0.0
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
        if live_observation_available and cloud_cover is not None and observed_cloud is not None
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
    path_residuals = observation_path_residuals(
        hourly,
        obs_today,
        timezone_name,
        target,
        as_of,
    )
    (
        effective_temperature_residual,
        temperature_anchor_gain,
        temperature_anchor_streak,
        recent_temperature_residual,
    ) = temperature_anchor_profile(
        path_residuals,
        temperature_anomaly,
        hours_to_peak,
    )
    unphased_temperature_residual = effective_temperature_residual
    phase_amplitude = phase_vs_amplitude_regime(
        hourly,
        obs_today,
        timezone_name=timezone_name,
        target=target,
        as_of=as_of,
        hours_to_peak=hours_to_peak,
        profile=(
            phase_amplitude_profile
            if "phase_vs_amplitude" not in _disabled_factors
            else None
        ),
    )
    if phase_amplitude["active"] and effective_temperature_residual is not None:
        blend = float(phase_amplitude["anchor_blend"])
        shifted_level = float(phase_amplitude["level_residual_after_shift_c"])
        effective_temperature_residual = (
            (1.0 - blend) * effective_temperature_residual
            + blend * shifted_level
        )
        shift_hours = float(phase_amplitude["phase_shift_hours"])
        if peak_at is not None:
            peak_at = peak_at - timedelta(hours=shift_hours)
            hours_to_peak = (
                peak_at - as_of_utc.to_pydatetime()
            ).total_seconds() / 3600
    phase_anchor_delta = (
        temperature_anchor_gain
        * (
            float(effective_temperature_residual)
            - float(unphased_temperature_residual)
        )
        if phase_amplitude["active"]
        and effective_temperature_residual is not None
        and unphased_temperature_residual is not None
        else 0.0
    )
    observed_dewpoint_trend = dewpoint_trend(obs_today)
    post_convective = post_convective_uncertainty(
        observations,
        as_of,
        (
            post_convective_profile
            if "post_convective_uncertainty" not in _disabled_factors
            else None
        ),
    )
    post_convective_active = bool(
        post_convective["active"] and target == local_now.date()
    )
    (
        late_dry_mixing,
        late_dry_mixing_signal,
        model_ceiling_reached_early,
    ) = late_dry_mixing_adjustment(
        obs_today,
        corrected_model_mean=corrected.mean,
        local_now=local_now,
        hours_to_window_end=hours_to_window_end,
        wind_speed_kph=wind_speed,
    )
    failed_convection, failed_convection_signal = failed_convection_adjustment(
        obs_today,
        taf_guidance,
        local_now,
        hours_to_peak,
    )
    clear_sky_override, clear_sky_signal = clear_sky_override_adjustment(
        obs_today,
        model_cloud_cover=cloud_cover,
        taf_guidance=taf_guidance,
    )
    if "clear_sky_override" in _disabled_factors:
        clear_sky_override, clear_sky_signal = 0.0, None
    maritime_advection = maritime_advection_regime(
        obs_today,
        profile=(
            maritime_advection_profile
            if "maritime_advection" not in _disabled_factors
            else None
        ),
    )
    maritime_low_range = maritime_low_range_regime(
        obs_today,
        local_now=local_now,
        profile=(
            maritime_low_range_profile
            if "maritime_low_range" not in _disabled_factors
            else None
        ),
    )

    def limited(value: float | None, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value))) if value is not None else 0.0

    observed_wind_adjustment = (
        wind_heat_adjustment(
            speed_kph=wind_speed,
            direction_deg=wind_direction,
            warm_sectors=wind_profile.get("warm_sectors"),
            cool_sectors=wind_profile.get("cool_sectors"),
            source=wind_source or "model",
        )
        if live_observation_available and wind_source == "METAR"
        else 0.0
    )
    if late_dry_mixing > 0 and observed_wind_adjustment < 0:
        # A nominal cooling-sector wind must not erase observed warm, dry
        # entrainment once the station itself confirms that regime.
        observed_wind_adjustment = 0.0

    contributions = {
        "temperature_anchor": limited(
            temperature_anchor_gain * effective_temperature_residual
            if effective_temperature_residual is not None
            else None,
            -1.40,
            1.40,
        ),
        "dryness": limited(
            0.025 * dryness_surprise if dryness_surprise is not None else None,
            -0.20,
            0.20,
        ),
        "dewpoint_trend": limited(
            -0.08 * observed_dewpoint_trend
            if live_observation_available and observed_dewpoint_trend is not None
            else None,
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
        "wind": observed_wind_adjustment,
        "run_trend": limited(
            0.15 * trend if live_observation_available and trend is not None else None,
            -0.20,
            0.20,
        ),
        "late_dry_mixing": (
            late_dry_mixing if live_observation_available else 0.0
        ),
        "failed_convection": (failed_convection if live_observation_available else 0.0),
        "clear_sky_override": (
            clear_sky_override if live_observation_available else 0.0
        ),
        "maritime_advection": 0.0,
    }
    contributions = _protect_persistent_anchor(
        contributions,
        anchor_streak=temperature_anchor_streak,
    )
    if live_observation_available and maritime_advection["active"]:
        contributions = _damp_positive_contributions(
            contributions,
            float(maritime_advection["positive_factor_multiplier"]),
        )
        contributions["maritime_advection"] = float(
            maritime_advection["center_adjustment_c"]
        )
    if live_observation_available and maritime_low_range["active"]:
        contributions = _damp_positive_contributions(
            contributions,
            float(maritime_low_range["positive_factor_multiplier"]),
        )
    adjustments = _scaled_live_adjustments(contributions)
    live_adjustment = adjustments["total"]
    heat = HeatSpikeAssessment(
        heat.score,
        heat.status,
        live_adjustment,
        [
            *heat.signals,
            *(
                [
                    "Observed maximum has reached the model ceiling with at least "
                    "two configured heating hours left"
                ]
                if model_ceiling_reached_early
                else []
            ),
            *([late_dry_mixing_signal] if late_dry_mixing_signal else []),
            *([failed_convection_signal] if failed_convection_signal else []),
            *([clear_sky_signal] if clear_sky_signal else []),
            *(
                [
                    "Rapid heat-ramp regime: positive historical warm-bias "
                    "corrections are reduced and bucket uncertainty is broadened"
                ]
                if rapid_heat["active"]
                else []
            ),
            *(
                [
                    "Warm regional-model cluster is kept separate from the "
                    "cooler global-model cluster"
                ]
                if cluster["active"]
                else []
            ),
            *(
                [
                    "Persistent-hot regime: established station heat, TAF guidance "
                    "and the warm regional-model cluster weaken normal warm-bias removal"
                ]
                if persistent_hot["active"]
                else []
            ),
            *(
                [
                    "Phase-dominant METAR path: the model curve is shifted in time "
                    "instead of transferring the full morning residual to Tmax"
                ]
                if phase_amplitude["active"]
                else []
            ),
            *(
                [
                    "Maritime advection override: strengthening sea-sector wind and "
                    "a temperature plateau reduce the remaining heating tail"
                ]
                if maritime_advection["active"]
                else []
            ),
            *(
                [
                    "Maritime low-range regime: stable strong sea wind suppresses "
                    "positive live corrections and narrows the distribution"
                ]
                if maritime_low_range["active"]
                else []
            ),
            *(
                [
                    "Post-convective regime: bucket uncertainty is broadened "
                    "without shifting the forecast centre"
                ]
                if post_convective_active
                else []
            ),
        ],
    )
    signed = [
        value for name, value in adjustments.items() if name != "total" and abs(value) >= 0.05
    ]
    contradictory = any(value > 0 for value in signed) and any(value < 0 for value in signed)
    live_sigma_floor = 0.80 if contradictory else 0.60 if len(signed) >= 4 else 0.65
    if rapid_heat["active"]:
        live_sigma_floor = max(live_sigma_floor, corrected.spread)
    if post_convective_active:
        live_sigma_floor = max(
            live_sigma_floor,
            corrected.spread * float(post_convective["spread_multiplier"]),
        )
    if maritime_low_range["active"] and not post_convective_active:
        live_sigma_floor = max(
            0.50,
            live_sigma_floor * float(maritime_low_range["spread_multiplier"]),
        )
    metar_unconditioned = consensus(
        (current.corrected_max + live_adjustment).tolist(),
        weights=current.model_weight.tolist(),
        sigma_floor=live_sigma_floor,
    )
    effective_remaining_rise = remaining_rise
    for regime in (maritime_advection, maritime_low_range):
        cap = regime.get("remaining_rise_cap_c")
        if regime["active"] and cap is not None:
            effective_remaining_rise = (
                float(cap)
                if effective_remaining_rise is None
                else min(float(effective_remaining_rise), float(cap))
            )
    remaining_rise = effective_remaining_rise
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
        "effective_temperature_residual_c": effective_temperature_residual,
        "recent_temperature_residual_c": recent_temperature_residual,
        "temperature_anchor_gain": temperature_anchor_gain,
        "temperature_anchor_streak": float(temperature_anchor_streak),
        "observed_dryness_c": observed_dryness,
        "model_dryness_c": model_dryness,
        "dryness_surprise_c": dryness_surprise,
        "observed_dewpoint_trend_cph": observed_dewpoint_trend,
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
        "hours_to_critical_window_end": hours_to_window_end,
        "model_ceiling_reached_early": float(model_ceiling_reached_early),
        "late_dry_mixing_active": float(late_dry_mixing > 0),
        "late_dry_mixing_adjustment_c": late_dry_mixing,
        "failed_convection_active": float(failed_convection > 0),
        "failed_convection_adjustment_c": failed_convection,
        "clear_sky_override_active": float(clear_sky_override > 0),
        "clear_sky_override_adjustment_c": clear_sky_override,
        "rapid_heat_ramp_active": float(bool(rapid_heat["active"])),
        "rapid_heat_ramp_forecast_vs_latest_c": rapid_heat[
            "forecast_vs_latest_c"
        ],
        "rapid_heat_ramp_latest_actual_change_c": rapid_heat[
            "latest_actual_change_c"
        ],
        "rapid_heat_ramp_forecast_vs_two_back_c": rapid_heat[
            "forecast_vs_two_back_c"
        ],
        "rapid_heat_ramp_bias_multiplier": float(rapid_heat["bias_multiplier"]),
        "rapid_heat_ramp_spread_multiplier": float(
            rapid_heat["spread_multiplier"]
        ),
        "rapid_heat_ramp_adjustment_c": rapid_heat_adjustment,
        "persistent_hot_active": float(bool(persistent_hot["active"])),
        "persistent_hot_latest_actual_c": persistent_hot["latest_actual_c"],
        "persistent_hot_recent_baseline_c": persistent_hot["recent_baseline_c"],
        "persistent_hot_latest_anomaly_c": persistent_hot["latest_anomaly_c"],
        "persistent_hot_forecast_vs_latest_c": persistent_hot[
            "forecast_vs_latest_c"
        ],
        "persistent_hot_recent_warm_error_c": persistent_hot[
            "recent_warm_error_c"
        ],
        "persistent_hot_taf_support": float(bool(persistent_hot["taf_support"])),
        "persistent_hot_clear_support": float(bool(persistent_hot["clear_support"])),
        "persistent_hot_bias_multiplier": float(persistent_hot["bias_multiplier"]),
        "persistent_hot_spread_multiplier": float(
            persistent_hot["spread_multiplier"]
        ),
        "persistent_hot_adjustment_c": persistent_hot_adjustment,
        "regional_cluster_active": float(bool(cluster["active"])),
        "regional_cluster_mean_gap_c": cluster["mean_gap_c"],
        "regional_cluster_weight_multiplier": float(cluster["multiplier"]),
        "regional_cluster_adjustment_c": regional_cluster_adjustment,
        "post_convective_uncertainty_active": float(post_convective_active),
        "post_convective_reports_48h": float(post_convective["reports"]),
        "hours_since_latest_convection": post_convective["hours_since_latest"],
        "post_convective_spread_multiplier": float(
            post_convective["spread_multiplier"]
        ),
        "phase_vs_amplitude_active": float(bool(phase_amplitude["active"])),
        "phase_vs_amplitude_classification": phase_amplitude["classification"],
        "phase_shift_hours": float(phase_amplitude["phase_shift_hours"]),
        "phase_same_time_residual_c": phase_amplitude["same_time_residual_c"],
        "phase_level_residual_after_shift_c": phase_amplitude[
            "level_residual_after_shift_c"
        ],
        "phase_baseline_rmse_c": phase_amplitude["baseline_rmse_c"],
        "phase_fit_rmse_c": phase_amplitude["phase_rmse_c"],
        "phase_anchor_blend": float(phase_amplitude["anchor_blend"]),
        "phase_anchor_delta_c": phase_anchor_delta,
        "maritime_advection_active": float(bool(maritime_advection["active"])),
        "maritime_advection_temperature_rate_cph": maritime_advection[
            "temperature_rate_cph"
        ],
        "maritime_advection_wind_speed_kph": maritime_advection["wind_speed_kph"],
        "maritime_advection_wind_speed_change_kph": maritime_advection[
            "wind_speed_change_kph"
        ],
        "maritime_advection_fraction": maritime_advection["maritime_fraction"],
        "maritime_advection_adjustment_c": float(
            maritime_advection["center_adjustment_c"]
        ),
        "maritime_low_range_active": float(bool(maritime_low_range["active"])),
        "maritime_low_range_recent_range_c": maritime_low_range["recent_range_c"],
        "maritime_low_range_daily_range_c": maritime_low_range["daily_range_c"],
        "maritime_low_range_median_wind_kph": maritime_low_range["median_wind_kph"],
        "maritime_low_range_sea_wind_fraction": maritime_low_range[
            "sea_wind_fraction"
        ],
        "maritime_low_range_spread_multiplier": float(
            maritime_low_range["spread_multiplier"]
        ),
    }
    if not d1_scored.empty:
        residual_errors = d1_scored.copy()
        residual_errors["residual_abs_error"] = (
            residual_errors.error - residual_errors.groupby("model").error.transform("mean")
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
        max(0.0, min(100.0, 100 - 35 * historical_mae)) if historical_mae is not None else 50.0
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
        "model_freshness": (
            max(0.0, min(100.0, 115 - latest_forecast_age_minutes))
            if latest_forecast_age_minutes is not None
            else 0.0
        ),
    }
    base_confidence = (
        0.40 * history_score + 0.30 * spread_score + 0.20 * sample_score + 0.10 * live_score
    )
    if taf_guidance is not None:
        confidence_factors["taf_guidance"] = float(taf_guidance.confidence_score)
        forecast_confidence = round(0.80 * base_confidence + 0.20 * taf_guidance.confidence_score)
    else:
        forecast_confidence = round(base_confidence)
    if forecast_data_stale:
        forecast_confidence = min(40, forecast_confidence)
    if post_convective_active and not day_status.is_locked:
        confidence_factors["post_convective_regime"] = 35.0
        forecast_confidence = round(
            forecast_confidence * float(post_convective["confidence_multiplier"])
        )
    if rapid_heat["active"] and not day_status.is_locked:
        confidence_factors["rapid_heat_ramp_regime"] = 45.0
        forecast_confidence = round(
            forecast_confidence * float(rapid_heat["confidence_multiplier"])
        )
    if persistent_hot["active"] and not day_status.is_locked:
        confidence_factors["persistent_hot_regime"] = 50.0
        forecast_confidence = round(
            forecast_confidence * float(persistent_hot["confidence_multiplier"])
        )
    if maritime_advection["active"] and not day_status.is_locked:
        confidence_factors["maritime_advection_regime"] = 55.0
        forecast_confidence = round(
            forecast_confidence * float(maritime_advection["confidence_multiplier"])
        )
    if maritime_low_range["active"] and not day_status.is_locked:
        confidence_factors["maritime_low_range_regime"] = 70.0
        forecast_confidence = round(
            forecast_confidence * float(maritime_low_range["confidence_multiplier"])
        )

    challenger_variants: dict[str, dict[str, object]] = {}
    active_challengers = {
        "rapid_heat_ramp": bool(rapid_heat["active"]),
        "regional_cluster": bool(cluster["active"]),
        "clear_sky_override": bool(clear_sky_override > 0),
        "post_convective_uncertainty": bool(post_convective_active),
        "persistent_hot": bool(persistent_hot["active"]),
        "phase_vs_amplitude": bool(phase_amplitude["active"]),
        "maritime_advection": bool(maritime_advection["active"]),
        "maritime_low_range": bool(maritime_low_range["active"]),
    }
    challenger_labels = {
        "rapid_heat_ramp": "Without Rapid Heat Ramp",
        "regional_cluster": "Without Regional Cluster",
        "clear_sky_override": "Without Clear-sky Override",
        "post_convective_uncertainty": "Without Post-Convective Uncertainty",
        "persistent_hot": "Without Persistent Hot",
        "phase_vs_amplitude": "Without Phase-vs-Amplitude",
        "maritime_advection": "Without Maritime Advection",
        "maritime_low_range": "Without Maritime Low-Range",
    }
    if _build_challengers:
        for factor, active in active_challengers.items():
            if not active:
                continue
            challenger = build_live_nowcast(
                forecasts=forecasts,
                actuals=actuals,
                observations=observations,
                hourly=hourly,
                markets=markets,
                tafs=tafs,
                timezone_name=timezone_name,
                target=target,
                as_of=as_of,
                wind_profile=wind_profile,
                routine_metar_minutes=routine_metar_minutes,
                critical_window_local=critical_window_local,
                post_convective_profile=post_convective_profile,
                heat_regime_profile=heat_regime_profile,
                phase_amplitude_profile=phase_amplitude_profile,
                maritime_advection_profile=maritime_advection_profile,
                maritime_low_range_profile=maritime_low_range_profile,
                maximum_model_age_minutes=maximum_model_age_minutes,
                _disabled_factors=frozenset({*_disabled_factors, factor}),
                _build_challengers=False,
            )
            if challenger is None:
                continue
            challenger_variants[challenger_labels[factor]] = {
                "factor": factor,
                "forecast_mean_c": challenger.final_forecast_mean,
                "spread_c": challenger.final_forecast_spread,
                "probabilities": challenger.probabilities,
                "forecast_confidence": challenger.forecast_confidence,
            }

    return LiveNowcast(
        current=current,
        model_freshness=model_freshness,
        forecast_data_stale=forecast_data_stale,
        fresh_model_count=fresh_model_count,
        stale_models=stale_models,
        latest_forecast_age_minutes=latest_forecast_age_minutes,
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
        challenger_variants=challenger_variants,
    )
