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
    daily = scored.groupby(["airport", "target_date"], as_index=False).agg(
        predicted=("max_temp_c_forecast", "median"), actual=("max_temp_c_actual", "first")
    )
    daily["bucket"] = daily.predicted.round().astype(int)
    daily["won"] = daily.actual.round().astype(int).eq(daily.bucket)
    daily["pnl"] = daily.won.map({True: stake * (decimal_odds - 1), False: -stake})
    daily["cumulative_pnl"] = daily.pnl.cumsum()
    return daily
