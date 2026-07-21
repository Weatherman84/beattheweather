from weatherman.settings import airports


def test_packaged_airports_are_available():
    catalog = airports()
    assert set(catalog) == {"LEMD", "EHAM", "EPWA", "LTAC"}
    assert "ukmo_global_deterministic_10km" in catalog["LEMD"]["models"]
    assert catalog["EHAM"]["heat_wind_profile"]["warm_sectors"] == [[60, 160]]
    assert catalog["EHAM"]["heat_wind_profile"]["cool_sectors"] == [[220, 340]]
