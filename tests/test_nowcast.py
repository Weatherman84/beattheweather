import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from weatherman.nowcast import build_live_nowcast


def test_shared_nowcast_locks_completed_evening_peak():
    as_of = datetime(2026, 7, 20, 21, tzinfo=ZoneInfo("Europe/Madrid"))
    as_of_utc = as_of.astimezone(timezone.utc)
    target = as_of.date()
    forecasts = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": model,
                "run_at": as_of_utc - timedelta(minutes=20),
                "target_date": target,
                "max_temp_c": maximum,
                "source": "open-meteo",
                "horizon": "Live",
            }
            for model, maximum in [("ECMWF", 36.0), ("GFS", 37.0)]
        ]
    )
    observations = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "observed_at": as_of_utc - timedelta(hours=2),
                "temp_c": 35.0,
                "dewpoint_c": 15.0,
            },
            {
                "airport": "LEMD",
                "observed_at": as_of_utc - timedelta(minutes=10),
                "temp_c": 32.0,
                "dewpoint_c": 15.0,
            },
        ]
    )
    hourly = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": model,
                "run_at": as_of_utc - timedelta(minutes=20),
                "valid_at": as_of_utc,
                "temp_c": 32.0,
                "cloud_cover": 0.0,
                "temp_850hpa_c": 18.0,
                "radiation_wm2": 0.0,
            }
            for model in ["ECMWF", "GFS"]
        ]
    )
    result = build_live_nowcast(
        forecasts=forecasts,
        actuals=pd.DataFrame(),
        observations=observations,
        hourly=hourly,
        markets=pd.DataFrame(),
        timezone_name="Europe/Madrid",
        target=target,
        as_of=as_of,
    )
    assert result is not None
    assert result.day_status.label == "Peak locked"
    assert result.probabilities == {35: 1.0}
    assert result.remaining_rise_c == 0


def test_taf_conflict_broadens_and_cautiously_lowers_live_distribution():
    as_of = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    target = as_of.date()
    forecasts = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": model,
                "run_at": as_of - timedelta(minutes=20),
                "target_date": target,
                "max_temp_c": maximum,
                "source": "open-meteo",
                "horizon": "Live",
            }
            for model, maximum in [("ECMWF", 39.0), ("GFS", 39.2)]
        ]
    )
    hourly = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": model,
                "run_at": as_of - timedelta(minutes=20),
                "valid_at": as_of,
                "temp_c": 34.0,
                "cloud_cover": 10.0,
                "temp_850hpa_c": 20.0,
                "radiation_wm2": 700.0,
                "wind_kph": 10.0,
                "wind_direction": 180.0,
            }
            for model in ["ECMWF", "GFS"]
        ]
    )
    common = {
        "forecasts": forecasts,
        "actuals": pd.DataFrame(),
        "observations": pd.DataFrame(),
        "hourly": hourly,
        "markets": pd.DataFrame(),
        "timezone_name": "Europe/Madrid",
        "target": target,
        "as_of": as_of,
    }
    without_taf = build_live_nowcast(**common)
    tafs = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "issue_time": as_of - timedelta(hours=1),
                "collected_at": as_of - timedelta(minutes=55),
                "valid_from": datetime(2026, 7, 21, 0, tzinfo=timezone.utc),
                "valid_to": datetime(2026, 7, 22, 6, tzinfo=timezone.utc),
                "raw_taf": "TAF LEMD TX36/2116Z TEMPO TSRA BKN030CB",
                "is_amended": False,
                "is_corrected": False,
                "max_temp_c": 36.0,
                "max_temp_at": datetime(2026, 7, 21, 16, tzinfo=timezone.utc),
                "periods_json": json.dumps(
                    [
                        {
                            "time_from": "2026-07-21T10:00:00+00:00",
                            "time_to": "2026-07-21T18:00:00+00:00",
                            "change": "TEMPO",
                            "weather": "TSRA",
                            "clouds": [{"cover": "BKN", "base": 3000, "type": "CB"}],
                        }
                    ]
                ),
            }
        ]
    )
    with_taf = build_live_nowcast(**common, tafs=tafs)
    assert without_taf is not None and with_taf is not None
    assert with_taf.corrected.mean == without_taf.corrected.mean
    assert with_taf.taf_guidance is not None
    assert with_taf.taf_guidance.agreement == "Contradicts model"
    mean_without = sum(k * v for k, v in without_taf.probabilities.items())
    mean_with = sum(k * v for k, v in with_taf.probabilities.items())
    assert mean_with < mean_without
    assert with_taf.metar_conditioned_mean == without_taf.metar_conditioned_mean
    assert abs(with_taf.taf_adjustment_c) <= 0.25
    assert with_taf.forecast_confidence < without_taf.forecast_confidence


def test_evening_model_path_is_anchored_to_metar_and_observed_maximum():
    as_of = datetime(2026, 7, 21, 21, tzinfo=ZoneInfo("Europe/Madrid"))
    as_of_utc = as_of.astimezone(timezone.utc)
    target = as_of.date()
    forecasts = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": "ECMWF",
                "run_at": as_of_utc - timedelta(minutes=20),
                "target_date": target,
                "max_temp_c": 38.0,
                "source": "open-meteo",
                "horizon": "Live",
            }
        ]
    )
    observations = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "observed_at": as_of_utc - timedelta(hours=2),
                "temp_c": 37.0,
                "dewpoint_c": 8.0,
            },
            {
                "airport": "LEMD",
                "observed_at": as_of_utc - timedelta(minutes=5),
                "temp_c": 35.0,
                "dewpoint_c": 8.0,
            },
        ]
    )
    hourly = pd.DataFrame(
        [
            {
                "airport": "LEMD",
                "model": "ECMWF",
                "run_at": as_of_utc - timedelta(minutes=20),
                "valid_at": valid_at,
                "temp_c": temp_c,
                "cloud_cover": 0.0,
                "temp_850hpa_c": 20.0,
                "radiation_wm2": 0.0,
            }
            for valid_at, temp_c in [
                (as_of_utc, 33.0),
                (as_of_utc + timedelta(hours=1), 34.0),
            ]
        ]
    )
    result = build_live_nowcast(
        forecasts=forecasts,
        actuals=pd.DataFrame(),
        observations=observations,
        hourly=hourly,
        markets=pd.DataFrame(),
        timezone_name="Europe/Madrid",
        target=target,
        as_of=as_of,
    )
    assert result is not None
    assert result.remaining_rise_c == 0
    assert result.day_status.label == "Peak locked"
    assert result.probabilities == {37: 1.0}
