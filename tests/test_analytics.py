import pandas as pd

from weatherman.analytics import consensus, flat_bet_simulation, model_metrics, score_frame


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
                "target_date": "2026-07-02",
                "max_temp_c_forecast": 35.1,
                "max_temp_c_actual": 35.0,
            },
            {
                "airport": "LEMD",
                "target_date": "2026-07-03",
                "max_temp_c_forecast": 36.2,
                "max_temp_c_actual": 35.0,
            },
        ]
    )
    result = flat_bet_simulation(scored)
    assert result.pnl.tolist() == [1.0, -1.0]
