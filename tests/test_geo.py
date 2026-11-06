"""Location resolution must reproduce HiringCafe's searchState byte-for-byte."""

import pytest

from app.errors import UnknownLocationError
from app.geo import resolve_us_zip

# The fixture was captured with radius=25, so the equality test pins that radius.
SAMPLE_ZIP = "83702"
SAMPLE_RADIUS = 25


def test_zip_reproduces_upstream_search_state(upstream_search_state):
    """The strongest test in the suite: our built location == what the live site echoed back."""
    expected = upstream_search_state["locations"][0]
    got = resolve_us_zip(SAMPLE_ZIP, radius=SAMPLE_RADIUS).to_search_state()
    assert got == expected


def test_location_identity_fields():
    state = resolve_us_zip(SAMPLE_ZIP).to_search_state()
    assert state["id"] == "us-zip-83702"
    assert state["postal_code"] == "83702"
    assert state["types"] == ["postal_code"]
    assert state["postal_code_source"] == "geonames"
    assert state["workplace_types"] == []


def test_formatted_address_and_components():
    state = resolve_us_zip(SAMPLE_ZIP).to_search_state()
    assert state["formatted_address"] == "Boise, ID, US"
    assert [c["types"][0] for c in state["address_components"]] == [
        "postal_code",
        "locality",
        "administrative_area_level_1",
        "country",
    ]
    zip_c, locality, admin1, country = state["address_components"]
    assert zip_c == {"long_name": "83702", "short_name": "83702", "types": ["postal_code"]}
    assert locality["long_name"] == "Boise"
    assert admin1 == {
        "long_name": "Idaho",
        "short_name": "ID",
        "types": ["administrative_area_level_1"],
    }
    assert country == {"long_name": "United States", "short_name": "US", "types": ["country"]}


def test_geometry_is_geonames_centroid():
    state = resolve_us_zip(SAMPLE_ZIP).to_search_state()
    assert state["geometry"]["location"] == {"lat": 43.6322, "lon": -116.2052}


def test_radius_and_units_are_configurable():
    state = resolve_us_zip(SAMPLE_ZIP, radius=25, radius_unit="km", ignore_radius=True).to_search_state()
    assert state["options"] == {"radius": 25, "radius_unit": "km", "ignore_radius": True}


def test_default_options():
    state = resolve_us_zip(SAMPLE_ZIP).to_search_state()
    assert state["options"] == {"radius": 50, "radius_unit": "miles", "ignore_radius": False}


@pytest.mark.parametrize("postal", ["00000", "00001", "99999"])
def test_unknown_postal_code_raises_404(postal):
    with pytest.raises(UnknownLocationError) as exc:
        resolve_us_zip(postal)
    assert exc.value.status_code == 404
    assert exc.value.code == "unknown_location"


def test_postal_code_is_normalized():
    assert resolve_us_zip(f" {SAMPLE_ZIP} ").postal_code == SAMPLE_ZIP


def test_injection_attempt_is_just_an_unknown_zip():
    """The lookup must be parameterized: a hostile string is a 404, not SQL and not a 500."""
    with pytest.raises(UnknownLocationError):
        resolve_us_zip("'; DROP TABLE zips;--")
    # and the database is still intact
    assert resolve_us_zip(SAMPLE_ZIP).postal_code == SAMPLE_ZIP


def test_missing_zip_database_is_a_server_error_not_a_404(tmp_path):
    """A missing DB is our fault (500), not the caller's (404) — the codes must not blur."""
    from app.errors import ZipDatabaseMissingError

    with pytest.raises(ZipDatabaseMissingError):
        resolve_us_zip(SAMPLE_ZIP, zipdb_path=tmp_path / "does-not-exist.db")
