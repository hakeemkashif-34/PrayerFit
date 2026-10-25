"""Tests for Photon (addresses and masjids), the rate limit, distances, and time zones. All faked."""

import logging
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo.errors import OsmServiceError
from app.geo.photon import suggest, suggest_masjids
from app.geo.distance import distance_km
from app.http_client import HTTP_TIMEOUT, new_http_client
from app.geo.timezones import timezone_for
from app.models import GeocodeCache
from tests.conftest import fake_http_client

NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
QUERY = "200 Kanata Ave"
HOME = (45.3088, -75.8987)  # a made-up point in Kanata


@pytest.fixture
def session(db):
    with Session(db, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def http(fake_google, fake_photon):
    with fake_http_client(fake_google, fake_photon) as client:
        yield client


# ---- Photon ----


def _add_kanata(fake_photon):
    fake_photon.add_place(
        43.1, -77.6, countrycode="US", housenumber="200", street="Kanata Avenue",
        city="Rochester", state="New York", country="United States",
    )
    fake_photon.add_place(
        *HOME, housenumber="200", street="Kanata Avenue", city="Ottawa",
        state="Ontario", postcode="K2T 1K8", country="Canada",
    )


def test_suggests_places_canada_first(session, http, fake_photon):
    _add_kanata(fake_photon)

    found = suggest(session, http, QUERY, NOW)

    # Photon sent the US one first. Canada is moved up.
    assert [s.label for s in found] == [
        "200 Kanata Avenue, Ottawa, Ontario, Canada",
        "200 Kanata Avenue, Rochester, New York, United States",
    ]
    assert (found[0].latitude, found[0].longitude) == HOME
    request = fake_photon.requests[0]
    assert request.headers["user-agent"] == "MuslimCalendar/0.4 (+mailto:tests@example.com)"
    assert request.url.params["q"] == QUERY


def test_postal_codes_are_never_shown(session, http, fake_photon):
    _add_kanata(fake_photon)
    # A postal code area, which Photon can also send. Its name is the postal code.
    fake_photon.add_place(*HOME, name="K2T 1K8", osm_value="postcode", city="Ottawa", country="Canada")

    found = suggest(session, http, "Kanata", NOW) + suggest(session, http, "K2T", NOW)

    assert found
    assert all("K2T" not in s.label and "1K8" not in s.label for s in found)


def test_at_most_5_suggestions(session, http, fake_photon):
    for n in range(8):
        fake_photon.add_place(45 + n / 100, -75.0, name=f"Kanata Place {n}", city="Ottawa", country="Canada")

    assert len(suggest(session, http, "Kanata", NOW)) == 5


def test_fewer_than_3_characters_never_calls_photon(session, http, fake_photon):
    assert suggest(session, http, "20", NOW) == []
    assert suggest(session, http, "  2  ", NOW) == []
    assert fake_photon.requests == []


def test_same_text_is_only_sent_once(session, http, fake_photon):
    _add_kanata(fake_photon)

    suggest(session, http, QUERY, NOW)
    # Different spacing and capitals are the same search.
    again = suggest(session, http, "  200 KANATA  ave ", NOW + timedelta(days=1))

    assert again[0].latitude == HOME[0]
    assert len(fake_photon.requests) == 1


def test_cache_runs_out_after_7_days(session, http, fake_photon):
    suggest(session, http, QUERY, NOW)
    suggest(session, http, QUERY, NOW + timedelta(days=8))
    assert len(fake_photon.requests) == 2


def test_no_match_is_empty_and_cached(session, http, fake_photon):
    assert suggest(session, http, "nowhere at all", NOW) == []
    assert suggest(session, http, "nowhere at all", NOW) == []
    assert len(fake_photon.requests) == 1


def test_duplicate_places_are_shown_once(session, http, fake_photon):
    _add_kanata(fake_photon)
    _add_kanata(fake_photon)
    assert len(suggest(session, http, QUERY, NOW)) == 2


def test_cache_never_holds_the_address_in_plain_text(session, http, fake_photon):
    _add_kanata(fake_photon)
    suggest(session, http, QUERY, NOW)

    row = session.scalars(select(GeocodeCache)).one()
    assert "kanata" not in row.query_hash.lower()
    assert b"Kanata" not in row.result_encrypted


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_busy_photon_gives_a_message_without_the_address(session, http, fake_photon, failure):
    fake_photon.failure = failure
    with pytest.raises(OsmServiceError) as error:
        suggest(session, http, QUERY, NOW)
    assert "Kanata" not in str(error.value)
    assert "Try again" in str(error.value)


def test_calls_are_spaced_out(session, http, fake_photon, throttle_waits, monkeypatch):
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


# ---- Distances ----


def test_distance_is_right():
    # Ottawa to Toronto is about 352 km in a straight line.
    assert distance_km(45.4215, -75.6972, 43.6532, -79.3832) == pytest.approx(352, abs=2)


# ---- Masjid suggestions ----


def _add_masjids(fake_photon):
    fake_photon.add_masjid(201, "Far Masjid", HOME[0] + 0.12, HOME[1], city="Ottawa")  # 13.3 km
    fake_photon.add_masjid(202, "Near Masjid", HOME[0] + 0.01, HOME[1], street="Sandhill Road", city="Ottawa")
    fake_photon.add_masjid(203, "Middle Masjid", HOME[0], HOME[1] + 0.07, osm_type="way", city="Ottawa")
    fake_photon.add_place(HOME[0] + 0.02, HOME[1], name="Masjid Street Park", city="Ottawa")  # not a place of worship


def test_masjid_suggestions_are_places_of_worship_closest_first(session, http, fake_photon):
    _add_masjids(fake_photon)

    found = suggest_masjids(session, http, "Masjid", HOME, NOW)

    assert [s.label for s in found] == ["Near Masjid", "Middle Masjid", "Far Masjid"]
    assert all(s.kind == "masjid" for s in found)
    assert found[0].street_address == "Sandhill Road, Ottawa"
    assert (found[0].osm_type, found[0].osm_id) == ("node", 202)
    assert (found[1].osm_type, found[1].osm_id) == ("way", 203)
    request = fake_photon.requests[0]
    assert request.url.params["osm_tag"] == "amenity:place_of_worship"
    assert request.headers["user-agent"] == "MuslimCalendar/0.4 (+mailto:tests@example.com)"


def test_masjid_search_is_biased_to_home_rounded_to_about_1_km(session, http, fake_photon):
    suggest_masjids(session, http, "Masjid", (45.30884, -75.89871), NOW)

    params = fake_photon.requests[0].url.params
    assert (params["lat"], params["lon"]) == ("45.31", "-75.9")


def test_at_most_5_masjid_suggestions(session, http, fake_photon):
    for n in range(8):
        fake_photon.add_masjid(300 + n, f"Masjid {n}", HOME[0] + n / 100, HOME[1])
    assert len(suggest_masjids(session, http, "Masjid", HOME, NOW)) == 5


def test_masjid_search_needs_3_characters(session, http, fake_photon):
    assert suggest_masjids(session, http, "Ma", HOME, NOW) == []
    assert fake_photon.requests == []


def test_a_name_only_needs_one_photon_call(session, http, fake_photon):
    _add_masjids(fake_photon)
    suggest_masjids(session, http, "Near", HOME, NOW)
    assert len(fake_photon.requests) == 1


def test_an_address_can_be_picked_when_no_masjid_matches(session, http, fake_photon):
    fake_photon.add_place(HOME[0] + 0.03, HOME[1], housenumber="10", street="Main Street", city="Ottawa", country="Canada")

    found = suggest_masjids(session, http, "10 Main", HOME, NOW)

    assert [(s.kind, s.label) for s in found] == [("address", "10 Main Street, Ottawa, Canada")]
    # 1 search for masjids, then 1 for addresses near home.
    assert [r.url.params.get("osm_tag") for r in fake_photon.requests] == ["amenity:place_of_worship", None]
    assert fake_photon.requests[1].url.params["lat"] == "45.31"


def test_text_with_a_number_adds_addresses_after_the_masjids(session, http, fake_photon):
    fake_photon.add_masjid(401, "Masjid 351", HOME[0] + 0.01, HOME[1], city="Ottawa")
    fake_photon.add_place(HOME[0] + 0.03, HOME[1], housenumber="351", street="Sandhill Road", city="Ottawa")

    found = suggest_masjids(session, http, "351", HOME, NOW)

    assert [s.kind for s in found] == ["masjid", "address"]


def test_masjid_suggestions_are_cached_per_area(session, http, fake_photon):
    _add_masjids(fake_photon)
    suggest_masjids(session, http, "Near", HOME, NOW)
    suggest_masjids(session, http, " near ", HOME, NOW + timedelta(days=6))
    assert len(fake_photon.requests) == 1

    # Someone in Toronto typing the same name gets their own search.
    suggest_masjids(session, http, "Near", (43.65, -79.38), NOW)
    assert len(fake_photon.requests) == 2


def test_masjid_cache_runs_out_after_7_days(session, http, fake_photon):
    suggest_masjids(session, http, "Near", HOME, NOW)
    suggest_masjids(session, http, "Near", HOME, NOW + timedelta(days=8))
    assert len(fake_photon.masjid_requests()) == 2


def test_unnamed_places_of_worship_arent_suggested(session, http, fake_photon):
    fake_photon.add_masjid(501, None, HOME[0] + 0.01, HOME[1], street="Sandhill Road", city="Ottawa")
    found = suggest_masjids(session, http, "Sandhill", HOME, NOW)
    assert all(s.kind == "address" for s in found)


def test_masjid_search_failure_has_a_message_without_what_was_typed(session, http, fake_photon):
    fake_photon.failure = 503
    with pytest.raises(OsmServiceError) as error:
        suggest_masjids(session, http, "Kanata Muslim", HOME, NOW)
    assert "Kanata" not in str(error.value)
    assert "Try again" in str(error.value)


# ---- Timeouts and failure logs ----


def test_google_and_photon_use_the_10_second_timeout():
    with new_http_client() as client:
        assert HTTP_TIMEOUT == 10
        assert client.timeout.read == 10
        assert client.timeout.connect == 10


@pytest.mark.parametrize(
    "failure, reason", [(503, "status 503"), ("timeout", "timeout"), ("connect", "connection error")]
)
def test_photon_failure_logs_the_reason_and_time_but_not_the_address(session, http, fake_photon, caplog, failure, reason):
    caplog.set_level(logging.DEBUG)
    fake_photon.failure = failure

    with pytest.raises(OsmServiceError):
        suggest(session, http, QUERY, NOW)

    assert re.search(rf"Photon failed: {reason} after \d+\.\d s", caplog.text)
    assert "Kanata" not in caplog.text
    assert "200" not in caplog.text
