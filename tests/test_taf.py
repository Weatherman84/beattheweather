import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from weatherman.taf import (
    build_taf_guidance,
    taf_verification_frame,
    taf_verification_metrics,
)


def report(
    *,
    issue: datetime,
    maximum: float | None,
    maximum_at: datetime | None,
    clouds: list[dict] | None = None,
    weather: str | None = None,
    wind_direction: int | str = 240,
    gust: int | None = 25,
) -> dict:
    return {
        "airport": "LEMD",
        "issue_time": issue,
        "collected_at": issue + timedelta(minutes=5),
        "valid_from": datetime(2026, 7, 21, 0, tzinfo=timezone.utc),
        "valid_to": datetime(2026, 7, 22, 6, tzinfo=timezone.utc),
        "raw_taf": "TAF LEMD TEST",
        "is_amended": False,
        "is_corrected": False,
        "max_temp_c": maximum,
        "max_temp_at": maximum_at,
        "periods_json": json.dumps(
            [
                {
                    "time_from": "2026-07-21T10:00:00+00:00",
                    "time_to": "2026-07-21T18:00:00+00:00",
                    "change": "TEMPO",
                    "probability": 40,
                    "wind_direction": wind_direction,
                    "wind_speed_kt": 12,
                    "wind_gust_kt": gust,
                    "weather": weather,
                    "clouds": clouds or [],
                }
            ]
        ),
    }


def test_taf_conflict_is_limited_and_flags_peak_weather():
    as_of = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    tafs = pd.DataFrame(
        [
            report(
                issue=as_of - timedelta(hours=1),
                maximum=36,
                maximum_at=datetime(2026, 7, 21, 16, tzinfo=timezone.utc),
                clouds=[{"cover": "BKN", "base": 3000, "type": "CB"}],
                weather="TSRA",
            )
        ]
    )
    guidance = build_taf_guidance(
        tafs,
        timezone_name="Europe/Madrid",
        target=date(2026, 7, 21),
        as_of=as_of,
        model_mean=39,
        wind_profile={"warm_sectors": [[120, 230]], "cool_sectors": [[240, 60]]},
    )
    assert guidance is not None
    assert guidance.agreement == "Contradicts model"
    assert guidance.center_adjustment_c == -0.5
    assert guidance.spread_addition_c == 0.55
    assert guidance.thunderstorm_risk
    assert guidance.heat_score_points == -12


def test_taf_without_tx_guides_conditions_without_moving_temperature_center():
    as_of = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    tafs = pd.DataFrame(
        [
            report(
                issue=as_of - timedelta(hours=1),
                maximum=None,
                maximum_at=None,
                clouds=[{"cover": "NSC", "base": None, "type": None}],
                gust=None,
            )
        ]
    )
    guidance = build_taf_guidance(
        tafs,
        timezone_name="Europe/Madrid",
        target=date(2026, 7, 21),
        as_of=as_of,
        model_mean=39,
    )
    assert guidance is not None
    assert guidance.agreement == "Neutral · no TX issued"
    assert guidance.center_adjustment_c == 0
    assert guidance.cloud_risk == "No significant cloud near peak"


def test_taf_change_and_timing_verification_use_latest_available_report():
    target = date(2026, 7, 21)
    maximum_at = datetime(2026, 7, 21, 16, tzinfo=timezone.utc)
    tafs = pd.DataFrame(
        [
            report(
                issue=datetime(2026, 7, 20, 18, tzinfo=timezone.utc),
                maximum=37,
                maximum_at=maximum_at,
            ),
            report(
                issue=datetime(2026, 7, 20, 21, tzinfo=timezone.utc),
                maximum=38,
                maximum_at=maximum_at,
            ),
        ]
    )
    guidance = build_taf_guidance(
        tafs,
        timezone_name="Europe/Madrid",
        target=target,
        as_of=datetime(2026, 7, 20, 22, tzinfo=timezone.utc),
        model_mean=38,
    )
    assert guidance is not None
    assert guidance.change_summary == "TX changed +1 °C"

    actuals = pd.DataFrame(
        [{"airport": "LEMD", "target_date": target, "max_temp_c": 39.0}]
    )
    scored = taf_verification_frame(
        tafs,
        actuals,
        {"LEMD": "Europe/Madrid"},
    )
    assert len(scored) == 1
    assert scored.iloc[0].timing == "D-1"
    assert scored.iloc[0].max_temp_c_taf == 38
    metrics = taf_verification_metrics(scored)
    assert metrics.iloc[0].mae == 1
