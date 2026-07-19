from __future__ import annotations

import math
from dataclasses import dataclass

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


def consensus(
    values: list[float], biases: list[float] | None = None, sigma_floor: float = 0.65
) -> Consensus:
    if not values:
        raise ValueError("At least one forecast is required")
    corrected = [v - b for v, b in zip(values, biases or [0.0] * len(values))]
    series = pd.Series(corrected, dtype=float)
    mean, median = float(series.mean()), float(series.median())
    spread = max(float(series.std(ddof=0)), sigma_floor)
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
    if minimum_bucket is None:
        return probabilities
    possible = {
        bucket: probability
        for bucket, probability in probabilities.items()
        if bucket >= minimum_bucket
    }
    total = sum(possible.values())
    if total <= 0:
        return {minimum_bucket: 1.0}
    return {bucket: probability / total for bucket, probability in possible.items()}


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
    result["buy_price"] = result.best_ask.fillna(result.yes_price).astype(float)
    result["edge"] = result.model_probability - result.buy_price
    result["signal"] = "No clear edge"
    actionable = result.best_ask.notna()
    result.loc[actionable & (result.edge >= 0.04), "signal"] = "Watch"
    result.loc[actionable & (result.edge >= 0.08), "signal"] = "Possible edge"
    return result.sort_values("edge", ascending=False)


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
