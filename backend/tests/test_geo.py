"""Tests for Photon, Overpass, the rate limit, and time zones. All faked."""

import logging
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo.errors import OsmServiceError
from app.geo.photon import suggest
from app.geo.overpass import OVERPASS_TIMEOUT, cell_for, distance_km, nearby_masjids
from app.http_client import HTTP_TIMEOUT, new_http_client
from app.geo.timezones import timezone_for
from app.models import GeocodeCache, Masjid
from tests.conftest import fake_http_client

NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
QUERY = "200 Kanata Ave"
HOME = (45.3088, -75.8987)  # a made-up point in Kanata


@pytest.fixture
def session(db):
    with Session(db, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def http(fake_google, fake_osm):
    with fake_http_client(fake_google, fake_osm) as client:
        yield client


# ---- Photon ----


def _add_kanata(fake_osm):
    fake_osm.add_place(
        43.1, -77.6, countrycode="US", housenumber="200", street="Kanata Avenue",
        city="Rochester", state="New York", country="United States",
    )
    fake_osm.add_place(
        *HOME, housenumber="200", street="Kanata Avenue", city="Ottawa",
        state="Ontario", postcode="K2T 1K8", country="Canada",
    )


def test_suggests_places_canada_first(session, http, fake_osm):
    _add_kanata(fake_osm)

    found = suggest(session, http, QUERY, NOW)

    # Photon sent the US one first. Canada is moved up.
    assert [s.label for s in found] == [
        "200 Kanata Avenue, Ottawa, Ontario, Canada",
        "200 Kanata Avenue, Rochester, New York, United States",
    ]
    assert (found[0].latitude, found[0].longitude) == HOME
    request = fake_osm.photon_requests[0]
    assert request.headers["user-agent"] == "MuslimCalendar/0.4 (+mailto:tests@example.com)"
    assert request.url.params["q"] == QUERY


def test_postal_codes_are_never_shown(session, http, fake_osm):
    _add_kanata(fake_osm)
    # A postal code area, which Photon can also send. Its name is the postal code.
    fake_osm.add_place(*HOME, name="K2T 1K8", osm_value="postcode", city="Ottawa", country="Canada")

    found = suggest(session, http, "Kanata", NOW) + suggest(session, http, "K2T", NOW)

    assert found
    assert all("K2T" not in s.label and "1K8" not in s.label for s in found)


def test_at_most_5_suggestions(session, http, fake_osm):
    for n in range(8):
        fake_osm.add_place(45 + n / 100, -75.0, name=f"Kanata Place {n}", city="Ottawa", country="Canada")

    assert len(suggest(session, http, "Kanata", NOW)) == 5


def test_fewer_than_3_characters_never_calls_photon(session, http, fake_osm):
    assert suggest(session, http, "20", NOW) == []
    assert suggest(session, http, "  2  ", NOW) == []
    assert fake_osm.photon_requests == []


def test_same_text_is_only_sent_once(session, http, fake_osm):
    _add_kanata(fake_osm)

    suggest(session, http, QUERY, NOW)
    # Different spacing and capitals are the same search.
    again = suggest(session, http, "  200 KANATA  ave ", NOW + timedelta(days=1))

    assert again[0].latitude == HOME[0]
    assert len(fake_osm.photon_requests) == 1


def test_cache_runs_out_after_7_days(session, http, fake_osm):
    suggest(session, http, QUERY, NOW)
    suggest(session, http, QUERY, NOW + timedelta(days=8))
    assert len(fake_osm.photon_requests) == 2


def test_no_match_is_empty_and_cached(session, http, fake_osm):
    assert suggest(session, http, "nowhere at all", NOW) == []
    assert suggest(session, http, "nowhere at all", NOW) == []
    assert len(fake_osm.photon_requests) == 1


def test_duplicate_places_are_shown_once(session, http, fake_osm):
    _add_kanata(fake_osm)
    _add_kanata(fake_osm)
    assert len(suggest(session, http, QUERY, NOW)) == 2


def test_cache_never_holds_the_address_in_plain_text(session, http, fake_osm):
    _add_kanata(fake_osm)
    suggest(session, http, QUERY, NOW)

    row = session.scalars(select(GeocodeCache)).one()
    assert "kanata" not in row.query_hash.lower()
    assert b"Kanata" not in row.result_encrypted


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_busy_photon_gives_a_message_without_the_address(session, http, fake_osm, failure):
    fake_osm.photon_failure = failure
    with pytest.raises(OsmServiceError) as error:
        suggest(session, http, QUERY, NOW)
    assert "Kanata" not in str(error.value)
    assert "Try again" in str(error.value)


def test_calls_are_spaced_out(session, http, fake_osm, throttle_waits, monkeypatch):
    from app.geo import throttle

    # Freeze the clock so the second call is "right after" the first.
    monkeypatch.setattr(throttle, "utc_now", lambda: NOW)
    suggest(session, http, "first address", NOW)
    suggest(session, http, "second address", NOW)

    assert throttle_waits == [0.25]


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


@pytest.mark.parametrize("failure", [429, 504, "timeout", "connect"])
def test_busy_overpass_gives_a_friendly_message(session, http, fake_osm, failure):
    fake_osm.overpass_failure = failure
    with pytest.raises(OsmServiceError, match="Try again in a minute"):
        nearby_masjids(session, http, *HOME, NOW)


# ---- Timeouts and failure logs ----


def test_overpass_call_uses_a_60_second_timeout(session, http, fake_osm):
    nearby_masjids(session, http, *HOME, NOW)

    # The timeout httpx2 used for this one request, whatever the client's default is.
    timeout = fake_osm.overpass_requests[0].extensions["timeout"]
    assert OVERPASS_TIMEOUT == 60
    assert timeout == {"connect": 60, "read": 60, "write": 60, "pool": 60}


def test_google_and_photon_keep_the_10_second_timeout(session, http, fake_osm):
    with new_http_client() as client:
        assert HTTP_TIMEOUT == 10
        assert client.timeout.read == 10
        assert client.timeout.connect == 10
    # Photon doesn't set its own, so it uses the client's.
    suggest(session, http, QUERY, NOW)
    assert fake_osm.photon_requests[0].extensions["timeout"]["read"] != OVERPASS_TIMEOUT


def test_overpass_timeout_says_it_took_too_long(session, http, fake_osm):
    fake_osm.overpass_failure = "timeout"
    with pytest.raises(OsmServiceError, match="took too long"):
        nearby_masjids(session, http, *HOME, NOW)


@pytest.mark.parametrize(
    "failure, reason", [(504, "status 504"), (429, "status 429"), ("timeout", "timeout"), ("connect", "connection error")]
)
def test_overpass_failure_logs_the_reason_and_time_but_not_the_location(session, http, fake_osm, caplog, failure, reason):
    caplog.set_level(logging.DEBUG)
    fake_osm.overpass_failure = failure

    with pytest.raises(OsmServiceError):
        nearby_masjids(session, http, *HOME, NOW)

    assert re.search(rf"Overpass failed: {reason} after \d+\.\d s", caplog.text)
    for secret in ("45.3", "75.8", "75.9", "45.31", "-75.9"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "failure, reason", [(503, "status 503"), ("timeout", "timeout"), ("connect", "connection error")]
)
def test_photon_failure_logs_the_reason_and_time_but_not_the_address(session, http, fake_osm, caplog, failure, reason):
    caplog.set_level(logging.DEBUG)
    fake_osm.photon_failure = failure

    with pytest.raises(OsmServiceError):
        suggest(session, http, QUERY, NOW)

    assert re.search(rf"Photon failed: {reason} after \d+\.\d s", caplog.text)
    assert "Kanata" not in caplog.text
    assert "200" not in caplog.text
