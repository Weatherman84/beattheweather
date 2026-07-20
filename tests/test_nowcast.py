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
