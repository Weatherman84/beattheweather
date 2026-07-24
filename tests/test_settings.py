from weatherman.catalog import market_city_index, research_airports, trading_airports
from weatherman.settings import airports


def test_packaged_airports_are_available():
    catalog = airports()
    assert {"LEMD", "EHAM", "EPWA", "LTAC", "KDFW", "VHHH"} <= set(catalog)
    assert set(trading_airports()) == {"LEMD", "EHAM", "EPWA", "LTAC"}
    assert set(trading_airports()) < set(research_airports())
    assert "ukmo_global_deterministic_10km" in catalog["LEMD"]["models"]
    assert catalog["EHAM"]["heat_wind_profile"]["warm_sectors"] == [[60, 160]]
    assert catalog["EHAM"]["heat_wind_profile"]["cool_sectors"] == [[220, 340]]
    assert market_city_index()["nyc"][0] == "KNYC"
    assert market_city_index()["new-york-city"][0] == "KNYC"
