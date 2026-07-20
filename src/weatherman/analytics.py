from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd


@dataclass(frozen=True)
class Consensus:
    mean: float
    median: float
    spread: float
    probability_by_bucket: dict[int, float]


@dataclass(frozen=True)
class HeatSpikeAssessment:
    score: int
    status: str
    adjustment_c: float
    signals: list[str]


@dataclass(frozen=True)
class DayStatus:
    phase: str
    label: str
    is_locked: bool
    minimum_bucket: int | None
    maximum_bucket: int | None
    remaining_heating_c: float | None
    explanation: str


def consensus(
    values: list[float],
    biases: list[float] | None = None,
    sigma_floor: float = 0.65,
    weights: list[float] | None = None,
) -> Consensus:
    if not values:
        raise ValueError("At least one forecast is required")
    biases = biases or [0.0] * len(values)
    weights = weights or [1.0] * len(values)
    if len(biases) != len(values) or len(weights) != len(values):
        raise ValueError("Values, biases and weights must have the same length")
    corrected = [float(value - bias) for value, bias in zip(values, biases)]
    usable_weights = [max(0.0, float(weight)) for weight in weights]
    if sum(usable_weights) <= 0:
        usable_weights = [1.0] * len(values)
    weight_total = sum(usable_weights)
    mean = sum(value * weight for value, weight in zip(corrected, usable_weights)) / weight_total
    ordered = sorted(zip(corrected, usable_weights), key=lambda item: item[0])
    cumulative = 0.0
    median = ordered[-1][0]
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= weight_total / 2:
            median = value
            break
    variance = sum(
        weight * (value - mean) ** 2 for value, weight in zip(corrected, usable_weights)
    ) / weight_total
    spread = max(math.sqrt(variance), sigma_floor)
    lo, hi = math.floor(mean - 4 * spread), math.ceil(mean + 4 * spread)
    probabilities = {}

    def cdf(x: float) -> float:
        return 0.5 * (1 + math.erf((x - mean) / (spread * math.sqrt(2))))

    for bucket in range(lo, hi + 1):
        lower, upper = bucket - 0.5, bucket + 0.5
        probabilities[bucket] = cdf(upper) - cdf(lower)
    total = sum(probabilities.values())
    probabilities = {k: v / total for k, v in probabilities.items()}
    return Consensus(mean, median, spread, probabilities)


def condition_probabilities(
    probabilities: dict[int, float], minimum_bucket: int | None
) -> dict[int, float]:
    return condition_probability_range(probabilities, minimum_bucket, None)


def condition_probability_range(
    probabilities: dict[int, float],
    minimum_bucket: int | None,
    maximum_bucket: int | None,
) -> dict[int, float]:
    if minimum_bucket is None and maximum_bucket is None:
        return probabilities
    possible = {
        bucket: probability
        for bucket, probability in probabilities.items()
        if (minimum_bucket is None or bucket >= minimum_bucket)
        and (maximum_bucket is None or bucket <= maximum_bucket)
    }
    total = sum(possible.values())
    if total <= 0:
        fallback = minimum_bucket if minimum_bucket is not None else maximum_bucket
        return {fallback: 1.0} if fallback is not None else probabilities
    return {bucket: probability / total for bucket, probability in possible.items()}


def assess_day_status(
    *,
    target_date: date,
    local_now: datetime,
    observed_max: float | None,
    observation_age_hours: float | None,
    heating_rate: float | None,
    remaining_model_rise: float | None,
    future_radiation_max: float | None,
    resolved_lower_c: float | None = None,
    resolved_upper_c: float | None = None,
) -> DayStatus:
    """Decide whether a daily maximum can still change.

    The live lock is deliberately conservative: it requires a fresh observation, a
    non-rising temperature, almost no remaining sunlight and no meaningful rise in
    the latest hourly model paths. A settled market may supply an official range.
    """
    minimum_bucket = math.floor(observed_max + 0.5) if observed_max is not None else None
    has_resolution = resolved_lower_c is not None or resolved_upper_c is not None
    if has_resolution:
        resolved_min = math.ceil(resolved_lower_c) if resolved_lower_c is not None else None
        resolved_max = math.floor(resolved_upper_c) if resolved_upper_c is not None else None
        return DayStatus(
            phase="resolved",
            label="Officially resolved",
            is_locked=True,
            minimum_bucket=resolved_min,
            maximum_bucket=resolved_max,
            remaining_heating_c=0.0,
            explanation="The market is closed and its official winning range is available.",
        )

    if target_date < local_now.date():
        if minimum_bucket is not None:
            return DayStatus(
                phase="final",
                label="Final from observations",
                is_locked=True,
                minimum_bucket=minimum_bucket,
                maximum_bucket=minimum_bucket,
                remaining_heating_c=0.0,
                explanation="The local calendar day has ended; the stored METAR maximum is final.",
            )
        return DayStatus(
            phase="incomplete",
            label="Past day · observations missing",
            is_locked=False,
            minimum_bucket=None,
            maximum_bucket=None,
            remaining_heating_c=None,
            explanation="The date has passed, but no METAR maximum is stored for it.",
        )

    if target_date > local_now.date():
        return DayStatus(
            phase="forecast",
            label="Pre-day forecast",
            is_locked=False,
            minimum_bucket=None,
            maximum_bucket=None,
            remaining_heating_c=remaining_model_rise,
            explanation="The target day has not started in the airport's local time.",
        )

    fresh_observation = (
        observation_age_hours is not None and 0 <= observation_age_hours <= 2.0
    )
    late_enough = local_now.hour >= 16
    not_heating = heating_rate is not None and heating_rate <= 0.2
    sunlight_gone = future_radiation_max is not None and future_radiation_max <= 50
    models_done = remaining_model_rise is not None and remaining_model_rise <= 0.4
    if (
        minimum_bucket is not None
        and fresh_observation
        and late_enough
        and not_heating
        and sunlight_gone
        and models_done
    ):
        return DayStatus(
            phase="locked",
            label="Peak locked",
            is_locked=True,
            minimum_bucket=minimum_bucket,
            maximum_bucket=minimum_bucket,
            remaining_heating_c=max(0.0, remaining_model_rise),
            explanation=(
                "Fresh METAR observations are no longer rising, sunlight is nearly gone and "
                "the hourly models show no meaningful remaining warming."
            ),
        )

    if minimum_bucket is None:
        label = "Waiting for METAR"
        explanation = "No observation for the local target day has been stored yet."
    elif not fresh_observation:
        label = "Live · METAR stale"
        explanation = "The last observation is too old to decide whether the daily peak is final."
    else:
        label = "Heating window open"
        explanation = "Further warming is still possible; only already-impossible lower buckets are removed."
    return DayStatus(
        phase="active",
        label=label,
        is_locked=False,
        minimum_bucket=minimum_bucket,
        maximum_bucket=None,
        remaining_heating_c=remaining_model_rise,
        explanation=explanation,
    )


def resolved_market_range(
    markets: pd.DataFrame,
) -> tuple[float | None, float | None, str] | None:
    """Return the sole official winning range once every stored market is closed."""
    if markets.empty or "closed" not in markets or "yes_won" not in markets:
        return None
    latest = markets.copy()
    if "captured_at" in latest:
        latest = latest.sort_values("captured_at").drop_duplicates("market_id", keep="last")
    if not latest.closed.fillna(False).astype(bool).all():
        return None
    winners = latest[latest.yes_won.fillna(False).astype(bool)]
    if len(winners) != 1:
        return None
    winner = winners.iloc[0]

    def optional_number(value: object) -> float | None:
        return float(value) if pd.notna(value) else None

    return (
        optional_number(winner.bucket_low_c),
        optional_number(winner.bucket_high_c),
        str(winner.bucket_label),
    )


def probability_for_range(
    probabilities: dict[int, float],
    lower_c: float | None,
    upper_c: float | None,
) -> float:
    return sum(
        probability
        for bucket, probability in probabilities.items()
        if (lower_c is None or bucket >= lower_c) and (upper_c is None or bucket <= upper_c)
    )


def market_edges(probabilities: dict[int, float], markets: pd.DataFrame) -> pd.DataFrame:
    if markets.empty:
        return pd.DataFrame()
    result = markets.copy()

    def optional_number(value: object) -> float | None:
        return float(value) if pd.notna(value) else None

    result["model_probability"] = result.apply(
        lambda row: probability_for_range(
            probabilities,
            optional_number(row.bucket_low_c),
            optional_number(row.bucket_high_c),
        ),
        axis=1,
    )
    result["buy_price"] = result.best_ask.where(result.best_ask.notna(), result.yes_price).astype(
        float
    )
    result["edge"] = result.model_probability - result.buy_price
    result["signal"] = "No clear edge"
    actionable = result.best_ask.notna()
    if "closed" in result:
        actionable &= ~result.closed.fillna(False).astype(bool)
    result.loc[actionable & (result.edge >= 0.04), "signal"] = "Watch"
    result.loc[actionable & (result.edge >= 0.08), "signal"] = "Possible edge"
    return result.sort_values("edge", ascending=False)


def resolved_market_outcomes(markets: pd.DataFrame) -> pd.DataFrame:
    """Return outcomes only for events with exactly one confirmed winner."""
    if markets.empty:
        return pd.DataFrame(columns=["market_id", "yes_won"])
    outcomes = markets.copy()
    outcomes["captured_at"] = pd.to_datetime(outcomes.captured_at, utc=True)
    outcomes = outcomes.sort_values("captured_at").drop_duplicates("market_id", keep="last")
    if "event_slug" in outcomes:
        outcomes["event_key"] = outcomes.event_slug.astype(str)
    else:
        outcomes["event_key"] = "single-event"
    resolved_groups = []
    for _, event in outcomes.groupby("event_key"):
        event_closed = event.closed.fillna(False).astype(bool).all()
        winner_count = int(event.yes_won.fillna(False).astype(bool).sum())
        if event_closed and winner_count == 1:
            resolved_groups.append(event[["market_id", "yes_won"]])
    return (
        pd.concat(resolved_groups, ignore_index=True)
        if resolved_groups
        else pd.DataFrame(columns=["market_id", "yes_won"])
    )


def settled_signal_performance(
    signals: pd.DataFrame,
    markets: pd.DataFrame,
    stake: float = 1.0,
) -> pd.DataFrame:
    """Settle the first recorded Possible-edge entry for each market range."""
    columns = [
        "airport",
        "target_date",
        "market_id",
        "bucket_label",
        "captured_at",
        "timing",
        "model_probability",
        "buy_price",
        "edge",
        "won",
        "pnl",
        "cumulative_pnl",
    ]
    if signals.empty or markets.empty:
        return pd.DataFrame(columns=columns)
    candidates = signals[signals.signal == "Possible edge"].copy()
    candidates["buy_price"] = pd.to_numeric(candidates.buy_price, errors="coerce")
    candidates = candidates[(candidates.buy_price > 0) & (candidates.buy_price < 1)]
    if candidates.empty:
        return pd.DataFrame(columns=columns)
    candidates["captured_at"] = pd.to_datetime(candidates.captured_at, utc=True)
    entries = candidates.sort_values("captured_at").drop_duplicates("market_id", keep="first")

    outcomes = resolved_market_outcomes(markets)
    if outcomes.empty:
        return pd.DataFrame(columns=columns)

    settled = entries.merge(outcomes, on="market_id", how="inner")
    if settled.empty:
        return pd.DataFrame(columns=columns)
    settled["won"] = settled.yes_won.astype(bool)
    settled["pnl"] = settled.apply(
        lambda row: stake / row.buy_price - stake if row.won else -stake,
        axis=1,
    )
    settled = settled.sort_values("captured_at")
    settled["cumulative_pnl"] = settled.pnl.cumsum()
    return settled[columns].reset_index(drop=True)


def settled_probability_comparison(
    signals: pd.DataFrame,
    markets: pd.DataFrame,
) -> pd.DataFrame:
    """Compare journaled model and market probabilities after official resolution."""
    if signals.empty or markets.empty:
        return pd.DataFrame()
    snapshots = signals.copy()
    snapshots["captured_at"] = pd.to_datetime(snapshots.captured_at, utc=True)
    snapshots = snapshots.sort_values("captured_at").drop_duplicates(
        ["market_id", "timing"], keep="first"
    )
    outcomes = resolved_market_outcomes(markets)
    if outcomes.empty:
        return pd.DataFrame()
    result = snapshots.merge(outcomes, on="market_id", how="inner")
    if result.empty:
        return result
    result["outcome"] = result.yes_won.astype(bool).astype(float)
    result["model_brier"] = (result.model_probability - result.outcome) ** 2
    result["market_brier"] = (result.market_probability - result.outcome) ** 2
    result["model_market_gap"] = (
        result.model_probability - result.market_probability
    ).abs()
    return result


def _expected_calibration_error(frame: pd.DataFrame, bins: int = 5) -> float | None:
    if frame.empty:
        return None
    working = frame.copy()
    working["probability_bin"] = pd.cut(
        working.model_probability,
        bins=[index / bins for index in range(bins + 1)],
        include_lowest=True,
    )
    total = len(working)
    error = 0.0
    for _, group in working.groupby("probability_bin", observed=True):
        error += len(group) / total * abs(
            float(group.model_probability.mean()) - float(group.outcome.mean())
        )
    return error


def trading_airport_scorecards(
    performance: pd.DataFrame,
    probability_records: pd.DataFrame,
) -> pd.DataFrame:
    """Build gated airport trading statistics from independent target-day results."""
    airports = set()
    if not performance.empty:
        airports.update(performance.airport.astype(str).unique())
    if not probability_records.empty:
        airports.update(probability_records.airport.astype(str).unique())
    rows = []
    for airport in sorted(airports):
        trades = performance[performance.airport == airport].copy()
        probabilities = probability_records[
            probability_records.airport == airport
        ].copy()
        if not trades.empty:
            trades["target_date"] = pd.to_datetime(trades.target_date).dt.date
            daily = trades.groupby("target_date", as_index=False).agg(
                pnl=("pnl", "sum"),
                entries=("market_id", "count"),
            )
            daily = daily.sort_values("target_date")
            cumulative = daily.pnl.cumsum()
            drawdown = cumulative - cumulative.cummax().clip(lower=0)
            max_drawdown = abs(float(drawdown.min()))
            resolved_days = int(daily.target_date.nunique())
            entries = len(trades)
            total_pnl = float(trades.pnl.sum())
            roi = total_pnl / entries
            hit_rate = float(trades.won.mean())
            average_edge = float(trades.edge.mean())
            daily_mean = float(daily.pnl.mean())
            daily_std = float(daily.pnl.std(ddof=1)) if resolved_days >= 2 else 0.0
            risk_ratio = daily_mean / daily_std if daily_std > 0 else 0.0
            sharpe = risk_ratio if resolved_days >= 30 and daily_std > 0 else None
        else:
            resolved_days = 0
            entries = 0
            total_pnl = 0.0
            roi = None
            hit_rate = None
            average_edge = None
            max_drawdown = 0.0
            risk_ratio = 0.0
            sharpe = None

        probability_samples = len(probabilities)
        model_brier = (
            float(probabilities.model_brier.mean()) if probability_samples else None
        )
        market_brier = (
            float(probabilities.market_brier.mean()) if probability_samples else None
        )
        brier_advantage = (
            market_brier - model_brier
            if model_brier is not None and market_brier is not None
            else None
        )
        average_market_gap = (
            float(probabilities.model_market_gap.mean()) if probability_samples else None
        )
        calibration_error = (
            _expected_calibration_error(probabilities)
            if probability_samples >= 100 and resolved_days >= 30
            else None
        )

        if resolved_days < 10:
            confidence = "Not enough data"
            trade_score = None
        else:
            confidence = (
                "Provisional"
                if resolved_days < 30
                else "Developing"
                if resolved_days < 100
                else "More robust"
            )
            roi_score = 50 + 50 * math.tanh(float(roi or 0.0) * 2)
            risk_score = 50 + 50 * math.tanh(risk_ratio)
            brier_score = 50 + 50 * math.tanh(float(brier_advantage or 0.0) * 10)
            raw_score = 0.50 * roi_score + 0.25 * risk_score + 0.25 * brier_score
            drawdown_penalty = min(15.0, max_drawdown / max(1, entries) * 15)
            reliability = min(1.0, resolved_days / 30)
            trade_score = 50 + reliability * (raw_score - drawdown_penalty - 50)
            trade_score = max(0.0, min(100.0, trade_score))

        rows.append(
            {
                "airport": airport,
                "resolved_days": resolved_days,
                "entries": entries,
                "hit_rate": hit_rate,
                "pnl": total_pnl,
                "roi": roi,
                "max_drawdown": max_drawdown,
                "sharpe": sharpe,
                "average_edge": average_edge,
                "probability_samples": probability_samples,
                "model_brier": model_brier,
                "market_brier": market_brier,
                "brier_advantage": brier_advantage,
                "average_market_gap": average_market_gap,
                "calibration_error": calibration_error,
                "trade_score": trade_score,
                "confidence": confidence,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "airport",
            "resolved_days",
            "entries",
            "hit_rate",
            "pnl",
            "roi",
            "max_drawdown",
            "sharpe",
            "average_edge",
            "probability_samples",
            "model_brier",
            "market_brier",
            "brier_advantage",
            "average_market_gap",
            "calibration_error",
            "trade_score",
            "confidence",
        ],
    )


def heat_spike_assessment(
    *,
    forecast_mean: float,
    recent_baseline: float | None,
    run_trend: float | None,
    model_spread: float,
    observed_temp: float | None,
    observed_dewpoint: float | None,
    expected_temp_now: float | None,
    heating_rate: float | None,
    cloud_cover: float | None,
) -> HeatSpikeAssessment:
    score = 35
    signals: list[str] = []

    if recent_baseline is not None:
        anomaly = forecast_mean - recent_baseline
        if anomaly >= 4:
            score += 20
            signals.append(f"Forecast is {anomaly:.1f} °C above the recent baseline")
        elif anomaly >= 2:
            score += 10
            signals.append(f"Moderate heat anomaly of {anomaly:.1f} °C")

    if run_trend is not None:
        if run_trend >= 1:
            score += 15
            signals.append(f"Model runs moved {run_trend:+.1f} °C hotter")
        elif run_trend >= 0.3:
            score += 7
            signals.append(f"Model runs trend slightly hotter ({run_trend:+.1f} °C)")
        elif run_trend <= -0.5:
            score -= 8
            signals.append(f"Latest runs cooled by {run_trend:.1f} °C")

    if model_spread <= 1:
        score += 8
        signals.append("Strong model agreement")
    elif model_spread >= 2.5:
        score -= 10
        signals.append("Large model disagreement")

    if observed_temp is not None and observed_dewpoint is not None:
        depression = observed_temp - observed_dewpoint
        if depression >= 15:
            score += 12
            signals.append(f"Very dry mixed air (T−Td {depression:.0f} °C)")
        elif depression >= 10:
            score += 6
            signals.append(f"Dry air supports heating (T−Td {depression:.0f} °C)")

    observed_anomaly = None
    if observed_temp is not None and expected_temp_now is not None:
        observed_anomaly = observed_temp - expected_temp_now
        if observed_anomaly >= 1:
            score += 15
            signals.append(f"METAR is {observed_anomaly:+.1f} °C above the model path")
        elif observed_anomaly <= -1:
            score -= 15
            signals.append(f"METAR is {observed_anomaly:.1f} °C below the model path")

    if heating_rate is not None:
        if heating_rate >= 1.5:
            score += 12
            signals.append(f"Rapid heating of {heating_rate:.1f} °C/hour")
        elif heating_rate >= 0.6:
            score += 6
            signals.append(f"Heating continues at {heating_rate:.1f} °C/hour")
        elif heating_rate < 0:
            score -= 5
            signals.append("Temperature is no longer rising")

    if cloud_cover is not None:
        if cloud_cover <= 20:
            score += 8
            signals.append("Mostly clear at the current forecast hour")
        elif cloud_cover >= 70:
            score -= 12
            signals.append("Cloud cover suppresses heating")

    score = int(max(0, min(100, score)))
    adjustment = 0.0
    if observed_anomaly is not None:
        adjustment += 0.45 * observed_anomaly
    if run_trend is not None:
        adjustment += 0.2 * run_trend
    adjustment = max(-1.5, min(1.5, adjustment))

    if observed_temp is None:
        status = "Elevated" if score >= 65 else "Normal"
    elif score >= 70 and (observed_anomaly or 0) >= 0:
        status = "Confirmed"
    elif score >= 50:
        status = "On track"
    elif score >= 30:
        status = "At risk"
    else:
        status = "Failed"
    return HeatSpikeAssessment(score, status, adjustment, signals or ["No strong signal"])


def score_frame(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty or actuals.empty:
        return pd.DataFrame()
    latest = forecasts.sort_values("run_at").drop_duplicates(
        ["airport", "model", "target_date"], keep="last"
    )
    merged = latest.merge(actuals, on=["airport", "target_date"], suffixes=("_forecast", "_actual"))
    merged["error"] = merged["max_temp_c_forecast"] - merged["max_temp_c_actual"]
    merged["abs_error"] = merged["error"].abs()
    return merged


def model_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame(columns=["model", "n", "bias", "mae", "rmse", "hit_rate"])
    rows = []
    for model, frame in scored.groupby("model"):
        rows.append(
            {
                "model": model,
                "n": len(frame),
                "bias": frame.error.mean(),
                "mae": frame.abs_error.mean(),
                "rmse": math.sqrt((frame.error**2).mean()),
                "hit_rate": (frame.abs_error < 0.5).mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("mae")


def model_weight_map(
    scored: pd.DataFrame,
    lookback_days: int = 90,
    full_reliability_days: int = 30,
) -> dict[str, float]:
    """Create conservative recent-error weights, shrunk toward equal weighting."""
    if scored.empty:
        return {}
    recent = scored.copy()
    recent["target_date"] = pd.to_datetime(recent.target_date).dt.date
    cutoff = max(recent.target_date) - timedelta(days=lookback_days - 1)
    recent = recent[recent.target_date >= cutoff]
    recent["residual_error"] = recent.error - recent.groupby("model").error.transform("mean")
    recent["residual_abs_error"] = recent.residual_error.abs()
    grouped = recent.groupby("model", as_index=False).agg(
        n=("target_date", "nunique"),
        mae=("residual_abs_error", "mean"),
    )
    if grouped.empty:
        return {}
    baseline_mae = max(0.25, float(grouped.mae.median()))
    raw: dict[str, float] = {}
    for row in grouped.itertuples():
        reliability = min(1.0, float(row.n) / full_reliability_days)
        relative_precision = ((baseline_mae + 0.35) / (float(row.mae) + 0.35)) ** 2
        raw[str(row.model)] = max(
            0.4,
            min(2.5, 1.0 + reliability * (relative_precision - 1.0)),
        )
    total = sum(raw.values())
    return {model: value / total for model, value in raw.items()}


def walk_forward_ensemble(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    min_history_days: int = 20,
) -> pd.DataFrame:
    """Validate dynamic weights using only information available before each target day."""
    if forecasts.empty or actuals.empty:
        return pd.DataFrame()
    d1 = forecasts[forecasts.horizon == "D-1"].copy()
    scored = score_frame(d1, actuals)
    if scored.empty:
        return pd.DataFrame()
    scored["target_date"] = pd.to_datetime(scored.target_date).dt.date
    rows = []
    for airport, airport_frame in scored.groupby("airport"):
        for target in sorted(airport_frame.target_date.unique()):
            history = airport_frame[airport_frame.target_date < target]
            if history.target_date.nunique() < min_history_days:
                continue
            history_cutoff = target - timedelta(days=90)
            recent_history = history[history.target_date >= history_cutoff]
            today = airport_frame[airport_frame.target_date == target]
            weights = model_weight_map(recent_history)
            biases = recent_history.groupby("model").error.mean().to_dict()
            fallback_weight = min(weights.values()) * 0.5 if weights else 1.0
            corrected_values = []
            current_weights = []
            for row in today.itertuples():
                corrected_values.append(
                    float(row.max_temp_c_forecast) - float(biases.get(row.model, 0.0))
                )
                current_weights.append(float(weights.get(row.model, fallback_weight)))
            if not corrected_values:
                continue
            total_weight = sum(current_weights)
            prediction = sum(
                value * weight for value, weight in zip(corrected_values, current_weights)
            ) / total_weight
            actual = float(today.max_temp_c_actual.iloc[0])
            rows.append(
                {
                    "airport": airport,
                    "model": "Weighted ensemble",
                    "target_date": target,
                    "max_temp_c_forecast": prediction,
                    "max_temp_c_actual": actual,
                    "error": prediction - actual,
                    "abs_error": abs(prediction - actual),
                }
            )
    return pd.DataFrame(rows)


def forecast_scorecards(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    windows: tuple[int, ...] = (30, 90, 365),
) -> pd.DataFrame:
    """Build per-airport and per-model accuracy scorecards for fixed D-1 forecasts."""
    if forecasts.empty or actuals.empty:
        return pd.DataFrame()
    d1 = forecasts[forecasts.horizon == "D-1"].copy()
    scored = score_frame(d1, actuals)
    ensemble = walk_forward_ensemble(forecasts, actuals)
    metric_columns = [
        "airport",
        "model",
        "target_date",
        "max_temp_c_forecast",
        "max_temp_c_actual",
        "error",
        "abs_error",
    ]
    if not ensemble.empty:
        scored = pd.concat(
            [scored[metric_columns], ensemble[metric_columns]],
            ignore_index=True,
        )
    if scored.empty:
        return pd.DataFrame()
    scored["target_date"] = pd.to_datetime(scored.target_date).dt.date
    scored["bucket_hit"] = scored.apply(
        lambda row: math.floor(row.max_temp_c_forecast + 0.5)
        == math.floor(row.max_temp_c_actual + 0.5),
        axis=1,
    )
    scored["within_1c"] = scored.abs_error <= 1.0
    latest = max(scored.target_date)
    rows = []
    for window in windows:
        period = scored[scored.target_date >= latest - timedelta(days=window - 1)]
        for (airport, model), frame in period.groupby(["airport", "model"]):
            n = int(frame.target_date.nunique())
            bias = float(frame.error.mean())
            mae = float(frame.abs_error.mean())
            rmse = math.sqrt(float((frame.error**2).mean()))
            exact_hit = float(frame.bucket_hit.mean())
            within_1c = float(frame.within_1c.mean())
            mae_score = 100 / (1 + (mae / 1.0) ** 2)
            rmse_score = 100 / (1 + (rmse / 1.25) ** 2)
            raw_score = (
                0.35 * mae_score
                + 0.20 * rmse_score
                + 0.25 * exact_hit * 100
                + 0.20 * within_1c * 100
            )
            reliability = min(1.0, n / 30)
            forecast_score = 50 + reliability * (raw_score - 50)
            rows.append(
                {
                    "airport": str(airport),
                    "model": str(model),
                    "window_days": window,
                    "n": n,
                    "bias": bias,
                    "mae": mae,
                    "rmse": rmse,
                    "exact_hit": exact_hit,
                    "within_1c": within_1c,
                    "forecast_score": max(0.0, min(100.0, forecast_score)),
                    "data_quality": (
                        "Strong" if n >= 90 else "Moderate" if n >= 30 else "Limited"
                    ),
                }
            )
    return pd.DataFrame(rows)


def flat_bet_simulation(
    scored: pd.DataFrame, stake: float = 1.0, decimal_odds: float = 2.0
) -> pd.DataFrame:
    """Synthetic $1 strategy: bet rounded corrected consensus, fixed odds unless market history exists."""
    if scored.empty:
        return pd.DataFrame()
    working = scored.sort_values(["airport", "model", "target_date"]).copy()
    if "error" not in working:
        working["error"] = working.max_temp_c_forecast - working.max_temp_c_actual
    working["past_bias"] = working.groupby(["airport", "model"])["error"].transform(
        lambda values: values.expanding().mean().shift(1)
    )
    working["corrected"] = working.max_temp_c_forecast - working.past_bias.fillna(0)
    daily = working.groupby(["airport", "target_date"], as_index=False).agg(
        predicted=("corrected", "median"), actual=("max_temp_c_actual", "first")
    )
    daily["bucket"] = (daily.predicted + 0.5).apply(math.floor).astype(int)
    daily["actual_bucket"] = (daily.actual + 0.5).apply(math.floor).astype(int)
    daily["won"] = daily.actual_bucket.eq(daily.bucket)
    daily["pnl"] = daily.won.map({True: stake * (decimal_odds - 1), False: -stake})
    daily["cumulative_pnl"] = daily.pnl.cumsum()
    return daily
