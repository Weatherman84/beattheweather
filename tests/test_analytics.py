from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from weatherman.analytics import (
    assess_day_status,
    condition_probability_range,
    condition_probabilities,
    consensus,
    flat_bet_simulation,
    heat_spike_assessment,
    market_edges,
    model_metrics,
    probability_for_range,
    resolved_market_range,
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


def test_completed_day_locks_probability_to_observed_maximum():
    status = assess_day_status(
        target_date=date(2026, 7, 20),
        local_now=datetime(2026, 7, 20, 21, tzinfo=ZoneInfo("Europe/Madrid")),
        observed_max=35.0,
        observation_age_hours=0.4,
        heating_rate=-0.8,
        remaining_model_rise=0.1,
        future_radiation_max=0,
    )
    assert status.label == "Peak locked"
    assert status.is_locked
    assert condition_probability_range({35: 0.3, 36: 0.5, 37: 0.2}, 35, 35) == {
        35: 1.0
    }


def test_day_stays_open_while_sunlight_and_warming_remain():
    status = assess_day_status(
        target_date=date(2026, 7, 20),
        local_now=datetime(2026, 7, 20, 17, tzinfo=ZoneInfo("Europe/Madrid")),
        observed_max=35.0,
        observation_age_hours=0.3,
        heating_rate=0.0,
        remaining_model_rise=0.8,
        future_radiation_max=250,
    )
    assert status.label == "Heating window open"
    assert not status.is_locked
    assert status.maximum_bucket is None


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


def test_market_range_probabilities_and_actionable_edge():
    probabilities = {34: 0.1, 35: 0.3, 36: 0.5, 37: 0.1}
    assert probability_for_range(probabilities, None, 34) == 0.1
    assert probability_for_range(probabilities, 37, None) == 0.1
    markets = pd.DataFrame(
        [
            {
                "bucket_label": "36°C",
                "bucket_low_c": 36,
                "bucket_high_c": 36,
                "yes_price": 0.39,
                "best_ask": 0.41,
            }
        ]
    )
    result = market_edges(probabilities, markets)
    assert round(result.iloc[0].edge, 2) == 0.09
    assert result.iloc[0].signal == "Possible edge"


def test_closed_market_is_not_marked_as_an_edge_and_supplies_winner():
    markets = pd.DataFrame(
        [
            {
                "market_id": "1",
                "captured_at": "2026-07-20T21:00:00Z",
                "bucket_label": "35°C",
                "bucket_low_c": 35,
                "bucket_high_c": 35,
                "yes_price": 1.0,
                "best_ask": 1.0,
                "closed": True,
                "yes_won": True,
            },
            {
                "market_id": "2",
                "captured_at": "2026-07-20T21:00:00Z",
                "bucket_label": "36°C",
                "bucket_low_c": 36,
                "bucket_high_c": 36,
                "yes_price": 0.0,
                "best_ask": 0.01,
                "closed": True,
                "yes_won": False,
            },
        ]
    )
    result = market_edges({35: 1.0}, markets)
    assert set(result.signal) == {"No clear edge"}
    assert resolved_market_range(markets) == (35.0, 35.0, "35°C")

    status = assess_day_status(
        target_date=date(2026, 7, 20),
        local_now=datetime(2026, 7, 21, 9, tzinfo=ZoneInfo("Europe/Madrid")),
        observed_max=None,
        observation_age_hours=None,
        heating_rate=None,
        remaining_model_rise=None,
        future_radiation_max=None,
        resolved_lower_c=35,
        resolved_upper_c=35,
    )
    assert status.label == "Officially resolved"
    assert status.minimum_bucket == status.maximum_bucket == 35
