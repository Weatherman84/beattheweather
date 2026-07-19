import pandas as pd

from weatherman.analytics import (
    condition_probabilities,
    consensus,
    flat_bet_simulation,
    heat_spike_assessment,
    model_metrics,
    score_frame,
)


def test_consensus_bias_correction():
    result = consensus([35, 36, 37], [1, 0, -1])
    assert result.mean == 36
    assert abs(sum(result.probability_by_bucket.values()) - 1) < 1e-9


def test_scoring_and_metrics():
    forecasts = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": "a",
                "run_at": "2026-07-01",
                "target_date": "2026-07-02",
                "max_temp_c": 35,
            },
            {
                "airport": "LEMD",
                "model": "a",
                "run_at": "2026-07-01 12:00",
                "target_date": "2026-07-02",
                "max_temp_c": 36,
            },
        ]
    )
    actuals = pd.DataFrame([{"airport": "LEMD", "target_date": "2026-07-02", "max_temp_c": 35}])
    scored = score_frame(forecasts, actuals)
    assert len(scored) == 1
    assert model_metrics(scored).iloc[0].bias == 1


def test_flat_bet_simulation():
    scored = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": "test-model",
                "target_date": "2026-07-02",
                "max_temp_c_forecast": 35.1,
                "max_temp_c_actual": 35.0,
            },
            {
                "airport": "LEMD",
                "model": "test-model",
                "target_date": "2026-07-03",
                "max_temp_c_forecast": 36.2,
                "max_temp_c_actual": 35.0,
            },
        ]
    )
    result = flat_bet_simulation(scored)
    assert result.pnl.tolist() == [1.0, -1.0]


def test_metar_floor_removes_impossible_buckets():
    conditioned = condition_probabilities({34: 0.4, 35: 0.35, 36: 0.2, 37: 0.05}, 35)
    assert 34 not in conditioned
    assert abs(sum(conditioned.values()) - 1) < 1e-9
    assert round(conditioned[35], 3) == 0.583


def test_heat_spike_confirmation():
    result = heat_spike_assessment(
        forecast_mean=36,
        recent_baseline=31,
        run_trend=1.1,
        model_spread=0.8,
        observed_temp=34,
        observed_dewpoint=15,
        expected_temp_now=32.5,
        heating_rate=1.6,
        cloud_cover=10,
    )
    assert result.score >= 70
    assert result.status == "Confirmed"
    assert result.adjustment_c > 0
