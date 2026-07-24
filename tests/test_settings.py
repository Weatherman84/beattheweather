from weatherman.settings import airports, market_city_index, trading_airports


def test_packaged_airports_are_available():
    catalog = airports()
    assert {"LEMD", "EHAM", "EPWA", "LTAC", "KDFW", "VHHH"} <= set(catalog)
    assert set(trading_airports()) == {"LEMD", "EHAM", "EPWA", "LTAC"}
    assert "ukmo_global_deterministic_10km" in catalog["LEMD"]["models"]
    assert catalog["EHAM"]["heat_wind_profile"]["warm_sectors"] == [[60, 160]]
    assert catalog["EHAM"]["heat_wind_profile"]["cool_sectors"] == [[220, 340]]
    assert market_city_index()["nyc"][0] == "KNYC"
    assert market_city_index()["new-york-city"][0] == "KNYC"
