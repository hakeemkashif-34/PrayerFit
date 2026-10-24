"""Tests for Nominatim, Overpass, the rate limit, and time zones. All faked."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo.errors import OsmServiceError
from app.geo.nominatim import find_address
from app.geo.overpass import cell_for, distance_km, nearby_masjids
from app.geo.timezones import timezone_for
from app.models import GeocodeCache, Masjid
from tests.conftest import fake_http_client

NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
ADDRESS = "200 Kanata Ave, Ottawa"
HOME = (45.3088, -75.8987)  # a made-up point in Kanata


@pytest.fixture
def session(db):
    with Session(db, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def http(fake_google, fake_osm):
    with fake_http_client(fake_google, fake_osm) as client:
        yield client


# ---- Nominatim ----


def test_finds_an_address(session, http, fake_osm):
    fake_osm.add_place(ADDRESS, "200, Kanata Avenue, Kanata, Ottawa, Ontario, Canada", *HOME)

    found = find_address(session, http, ADDRESS, NOW)

    assert found.place_name == "200, Kanata Avenue, Kanata, Ottawa, Ontario, Canada"
    assert (found.latitude, found.longitude) == HOME
    request = fake_osm.nominatim_requests[0]
    assert request.headers["user-agent"] == "MuslimCalendar/0.4 (+mailto:tests@example.com)"


def test_same_address_is_only_looked_up_once(session, http, fake_osm):
    fake_osm.add_place(ADDRESS, "Kanata", *HOME)

    find_address(session, http, ADDRESS, NOW)
    # Different spacing and capitals are the same search.
    again = find_address(session, http, "  200 KANATA  ave, ottawa ", NOW + timedelta(days=1))

    assert again.latitude == HOME[0]
    assert len(fake_osm.nominatim_requests) == 1


def test_cache_runs_out_after_30_days(session, http, fake_osm):
    fake_osm.add_place(ADDRESS, "Kanata", *HOME)
    find_address(session, http, ADDRESS, NOW)
    find_address(session, http, ADDRESS, NOW + timedelta(days=31))
    assert len(fake_osm.nominatim_requests) == 2


def test_not_found_is_none_and_cached(session, http, fake_osm):
    assert find_address(session, http, "nowhere at all", NOW) is None
    assert find_address(session, http, "nowhere at all", NOW) is None
    assert len(fake_osm.nominatim_requests) == 1


def test_cache_never_holds_the_address_in_plain_text(session, http, fake_osm):
    fake_osm.add_place(ADDRESS, "200, Kanata Avenue, Kanata", *HOME)
    find_address(session, http, ADDRESS, NOW)

    row = session.scalars(select(GeocodeCache)).one()
    assert "kanata" not in row.query_hash.lower()
    assert b"Kanata" not in row.result_encrypted


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_busy_nominatim_gives_a_message_without_the_address(session, http, fake_osm, failure):
    fake_osm.nominatim_failure = failure
    with pytest.raises(OsmServiceError) as error:
        find_address(session, http, ADDRESS, NOW)
    assert "Kanata" not in str(error.value)
    assert "Try again" in str(error.value)


def test_calls_are_at_least_1_second_apart(session, http, fake_osm, throttle_waits, monkeypatch):
    from app.geo import throttle

    # Freeze the clock so the second call is "right after" the first.
    monkeypatch.setattr(throttle, "utc_now", lambda: NOW)
    find_address(session, http, "first address", NOW)
    find_address(session, http, "second address", NOW)

    assert throttle_waits == [1.0]


# ---- Time zones ----


@pytest.mark.parametrize(
    "lat, lon, zone",
    [
        (45.4215, -75.6972, "America/Toronto"),  # Ottawa
        (49.2827, -123.1207, "America/Vancouver"),
        (50.4452, -104.6189, "America/Regina"),  # no daylight saving
        (51.5074, -0.1278, "Europe/London"),
        (21.4225, 39.8262, "Asia/Riyadh"),  # Makkah
    ],
)
def test_time_zone_comes_from_the_location(lat, lon, zone):
    assert timezone_for(lat, lon) == zone


# ---- Overpass ----


def test_distance_is_right():
    # Ottawa to Toronto is about 352 km in a straight line.
    assert distance_km(45.4215, -75.6972, 43.6532, -79.3832) == pytest.approx(352, abs=2)


def test_nearby_masjids_are_closest_first_within_15_km(session, http, fake_osm):
    fake_osm.add_masjid(1, "Far Masjid", HOME[0] + 0.12, HOME[1])  # about 13.3 km north
    fake_osm.add_masjid(2, "Near Masjid", HOME[0] + 0.01, HOME[1])  # about 1.1 km
    fake_osm.add_masjid(3, "Too Far Masjid", HOME[0] + 0.15, HOME[1])  # about 16.7 km
    fake_osm.add_masjid(4, "Middle Masjid", HOME[0], HOME[1] + 0.07, osm_type="way")  # about 5.5 km

    nearby = nearby_masjids(session, http, *HOME, NOW)

    assert [n.masjid.name for n in nearby] == ["Near Masjid", "Middle Masjid", "Far Masjid"]
    assert [round(n.distance_km, 1) for n in nearby] == [1.1, 5.5, 13.3]


def test_masjids_are_saved_with_their_openstreetmap_ids(session, http, fake_osm):
    fake_osm.add_masjid(
        555, "Test Masjid", HOME[0] + 0.01, HOME[1], osm_type="way",
        **{"addr:housenumber": "10", "addr:street": "Main St", "addr:city": "Ottawa"},
    )
    fake_osm.add_masjid(556, None, HOME[0] + 0.02, HOME[1])

    nearby_masjids(session, http, *HOME, NOW)

    named, unnamed = session.scalars(select(Masjid).order_by(Masjid.osm_id)).all()
    assert (named.source, named.osm_type, named.osm_id) == ("openstreetmap", "way", 555)
    assert named.address == "10 Main St, Ottawa"
    # No name and no address on OpenStreetMap, so none are made up.
    assert (unnamed.name, unnamed.address) == (None, None)


def test_overpass_gets_a_rounded_cell_not_the_home(session, http, fake_osm):
    nearby_masjids(session, http, 45.30884, -75.89871, NOW)
    assert fake_osm.last_overpass_point() == (45.31, -75.9)


def test_every_point_in_a_cell_gets_the_full_15_km(session, http, fake_osm):
    # The home is near the edge of its cell, and the masjid is 14.9 km away on the far side.
    home = (45.3149, -75.8951)
    assert cell_for(*home) == (45.31, -75.9)
    fake_osm.add_masjid(1, "Edge Masjid", home[0] - 0.134, home[1])
    nearby = nearby_masjids(session, http, *home, NOW)
    assert [round(n.distance_km, 1) for n in nearby] == [14.9]


def test_overpass_results_are_cached_for_7_days(session, http, fake_osm):
    fake_osm.add_masjid(1, "Near Masjid", HOME[0] + 0.01, HOME[1])
    nearby_masjids(session, http, *HOME, NOW)
    nearby_masjids(session, http, HOME[0] + 0.001, HOME[1], NOW + timedelta(days=6))  # same cell
    assert len(fake_osm.overpass_requests) == 1

    nearby_masjids(session, http, *HOME, NOW + timedelta(days=8))
    assert len(fake_osm.overpass_requests) == 2


def test_a_masjid_found_twice_is_saved_once(session, http, fake_osm):
    fake_osm.add_masjid(1, "Near Masjid", HOME[0] + 0.01, HOME[1])
    nearby_masjids(session, http, *HOME, NOW)
    nearby_masjids(session, http, HOME[0] + 0.03, HOME[1], NOW)  # another cell, same masjid
    assert len(session.scalars(select(Masjid)).all()) == 1


@pytest.mark.parametrize("failure", [429, 504, "timeout"])
def test_busy_overpass_gives_a_friendly_message(session, http, fake_osm, failure):
    fake_osm.overpass_failure = failure
    with pytest.raises(OsmServiceError, match="Try again in a minute"):
        nearby_masjids(session, http, *HOME, NOW)
