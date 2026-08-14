from weatherman.catalog import market_city_index, research_airports, trading_airports
from weatherman.settings import airports, settings


def test_packaged_airports_are_available():
    catalog = airports()
    assert {"LEMD", "EHAM", "EPWA", "LTAC", "KDFW", "VHHH"} <= set(catalog)
    assert set(trading_airports()) == {
        "LEMD",
        "EHAM",
        "EPWA",
        "LTAC",
        "LTFM",
        "EDDM",
    }
    assert set(trading_airports()) < set(research_airports())
    assert "ukmo_global_deterministic_10km" in catalog["LEMD"]["models"]
    assert catalog["LTFM"]["station_match"] == "verified station"
    assert catalog["LTFM"]["critical_window_local"] == ["12:30", "17:30"]
    assert catalog["EDDM"]["station_match"] == "verified station"
    assert "icon_eu" in catalog["EDDM"]["models"]
    assert catalog["LTAC"]["critical_window_local"] == ["11:30", "18:30"]
    assert catalog["LTAC"]["post_convective_uncertainty"]["spread_multiplier"] == 1.5
    assert catalog["LEMD"]["heat_regime"]["positive_bias_multiplier"] == 0.4
    assert "meteofrance_arome_france_hd" in catalog["LEMD"]["heat_regime"][
        "regional_models"
    ]
    assert catalog["EDDM"]["heat_regime"]["spread_multiplier"] == 1.3
    assert catalog["LEMD"]["heat_regime"]["persistent_hot"][
        "maximum_actual_age_days"
    ] == 1
    assert catalog["EPWA"]["live_adjustment_guardrails"]["positive_total_cap_c"] == 0.75
    assert catalog["EDDM"]["recent_warm_bias_challenger"]["enabled"]
    assert catalog["EHAM"]["heat_wind_profile"]["warm_sectors"] == [[60, 160]]
    assert catalog["EHAM"]["heat_wind_profile"]["cool_sectors"] == [[220, 340]]
    assert market_city_index()["nyc"][0] == "KNYC"
    assert market_city_index()["new-york-city"][0] == "KNYC"
    assert settings.regime_memory_auto_promotion_enabled is True
