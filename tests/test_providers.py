from datetime import date, datetime, timezone

from weatherman import providers


AIRPORT = {
    "latitude": 52.166,
    "longitude": 20.967,
    "timezone": "Europe/Warsaw",
    "market_city": "warsaw",
}


def test_forecast_horizon_separates_tomorrow_from_later_days():
    run_at = datetime(2026, 7, 19, 9, tzinfo=timezone.utc)
    assert providers._forecast_horizon(run_at, date(2026, 7, 20), "Europe/Warsaw") == "D-1"
    assert providers._forecast_horizon(run_at, date(2026, 7, 21), "Europe/Warsaw") == "D-2+"


def test_previous_run_d1_aggregates_each_local_day(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_get",
        lambda *_args, **_kwargs: {
            "hourly": {
                "time": ["2026-07-18T12:00", "2026-07-18T15:00", "2026-07-19T12:00"],
                "temperature_2m_previous_day1": [29.0, 31.5, 28.0],
            }
        },
    )
    rows = providers.previous_run_d1(AIRPORT, "ecmwf_ifs025", date(2026, 7, 18), date(2026, 7, 19))
    assert [row["max_temp_c"] for row in rows] == [31.5, 28.0]
    assert all(row["horizon"] == "D-1" for row in rows)


def test_recent_metars_skips_incomplete_reports(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_get",
        lambda *_args, **_kwargs: [
            {"obsTime": None, "temp": 30},
            {"obsTime": 1_752_921_600, "temp": 31, "dewp": 14, "wspd": 10},
        ],
    )
    rows = providers.recent_metars("EPWA")
    assert len(rows) == 1
    assert rows[0]["temp_c"] == 31
    assert round(rows[0]["wind_kph"], 2) == 18.52


def test_polymarket_prices_parse_exact_and_boundary_ranges(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_get",
        lambda *_args, **_kwargs: {
            "resolutionSource": "https://example.test/station",
            "markets": [
                {
                    "id": "lower",
                    "slug": "lower-market",
                    "groupItemTitle": "25°C or below",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.10", "0.90"]',
                    "clobTokenIds": '["yes-lower", "no-lower"]',
                    "bestBid": 0.08,
                    "bestAsk": 0.11,
                    "closed": False,
                },
                {
                    "id": "exact",
                    "slug": "exact-market",
                    "groupItemTitle": "26°C",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.55", "0.45"]',
                    "clobTokenIds": '["yes-exact", "no-exact"]',
                    "bestBid": 0.53,
                    "bestAsk": 0.57,
                    "closed": False,
                },
            ],
        },
    )
    rows = providers.polymarket_prices(AIRPORT, date(2026, 7, 20))
    assert providers.polymarket_event_slug(AIRPORT, date(2026, 7, 20)).endswith(
        "warsaw-on-july-20-2026"
    )
    assert len(rows) == 2
    assert rows[0]["bucket_low_c"] is None
    assert rows[0]["bucket_high_c"] == 25
    assert rows[1]["bucket_low_c"] == rows[1]["bucket_high_c"] == 26
    assert rows[1]["token_id"] == "yes-exact"
