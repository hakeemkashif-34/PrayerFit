"""Tests for the setup questions and the settings endpoints.

Google, Photon, and Overpass are all faked.
"""

import logging
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.models import Masjid, UserJumuahMasjid, UserSettings, WeeklyMasjidPrayers
from tests.conftest import new_client, sign_in
from tests.setup_helpers import (
    HOME,
    HOME_PLACE,
    HOME_QUERY,
    add_home,
    add_nearby_masjids,
    setup_through_api,
)

DAY = date(2026, 10, 24)  # a Saturday


@pytest.fixture
def signed_in(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    return client


@pytest.fixture
def osm(fake_osm):
    add_home(fake_osm)
    add_nearby_masjids(fake_osm)
    return fake_osm


def save_home(client) -> None:
    """Type the address and pick the Canadian suggestion, like the website does."""
    suggestions = client.post("/setup/location/suggest", json={"query": HOME_QUERY}).json()["suggestions"]
    index = next(s["index"] for s in suggestions if s["label"] == HOME_PLACE)
    response = client.put("/settings/location", json={"query": HOME_QUERY, "index": index})
    assert response.status_code == 200


def _nearby_ids(client) -> dict[str, str]:
    return {m["name"]: m["id"] for m in client.get("/masjids/nearby").json()["masjids"]}


# ---- Location ----


def test_suggestions_while_typing(signed_in, osm):
    response = signed_in.post("/setup/location/suggest", json={"query": HOME_QUERY})

    assert response.status_code == 200
    assert response.json() == {
        "suggestions": [
            {"index": 0, "label": HOME_PLACE},  # Canada first
            {"index": 1, "label": "200 Kanata Avenue, Rochester, New York, United States"},
        ],
        "credit": "© OpenStreetMap contributors",
        "credit_url": "https://www.openstreetmap.org/copyright",
    }
    # Suggesting saves nothing. Only picking does.
    assert signed_in.get("/settings").json()["address"] is None


def test_short_text_gets_no_suggestions(signed_in, osm):
    response = signed_in.post("/setup/location/suggest", json={"query": "20"})

    assert response.json()["suggestions"] == []
    assert osm.photon_requests == []


def test_picking_a_suggestion_saves_it_without_a_second_lookup(signed_in, osm):
    signed_in.post("/setup/location/suggest", json={"query": HOME_QUERY})
    response = signed_in.put("/settings/location", json={"query": HOME_QUERY, "index": 0})

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["address"] == HOME_PLACE
    assert settings["place_name"] == HOME_PLACE
    assert settings["time_zone"] == "America/Toronto"
    assert settings["missing"] == ["masjid", "weekly"]
    assert len(osm.photon_requests) == 1  # picking used the cached answer
    assert response.json()["calendar"] is None  # nothing goes to Google during setup


def test_picking_a_place_not_in_the_list_is_refused(signed_in, osm):
    response = signed_in.put("/settings/location", json={"query": HOME_QUERY, "index": 4})
    assert response.status_code == 404


def test_time_zone_comes_from_the_location(signed_in, fake_osm):
    fake_osm.add_place(49.2827, -123.1207, name="Robson Street", city="Vancouver", country="Canada")

    response = signed_in.put("/settings/location", json={"query": "Robson Street", "index": 0})

    assert response.json()["settings"]["time_zone"] == "America/Vancouver"


def test_address_is_stored_encrypted(signed_in, osm, db):
    save_home(signed_in)

    with db.connect() as connection:
        raw = connection.execute(
            text("SELECT address_encrypted, place_name_encrypted, location_encrypted FROM user_settings")
        ).one()
    for value in raw:
        assert b"Kanata" not in value
        assert b"45.3088" not in value
        assert value.startswith(b"gAAAAA")  # what every Fernet token starts with


def test_address_never_shows_up_in_logs(signed_in, osm, caplog):
    caplog.set_level(logging.DEBUG)

    setup_through_api(signed_in, osm)

    assert "Kanata" not in caplog.text
    assert "45.3088" not in caplog.text


def test_busy_photon_is_a_503_with_a_message(signed_in, fake_osm):
    fake_osm.photon_failure = 429

    response = signed_in.post("/setup/location/suggest", json={"query": HOME_QUERY})

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "The address search is busy. Try again in a minute."


# ---- Methods ----


def test_methods_default_to_isna_and_standard(signed_in):
    # Not asked in setup, so the defaults apply until the user changes them.
    settings = signed_in.get("/settings").json()
    assert (settings["method"], settings["asr_method"]) == ("isna", "standard")

    response = signed_in.put("/settings/methods", json={})
    settings = response.json()["settings"]
    assert (settings["method"], settings["asr_method"]) == ("isna", "standard")


def test_methods_save(signed_in):
    signed_in.put("/settings/methods", json={"method": "mwl", "asr_method": "hanafi"})

    settings = signed_in.get("/settings").json()
    assert (settings["method"], settings["asr_method"]) == ("mwl", "hanafi")


def test_unknown_method_is_rejected(signed_in):
    assert signed_in.put("/settings/methods", json={"method": "made-up"}).status_code == 422


# ---- Main masjid ----


def test_nearby_masjids_are_sorted_by_distance(signed_in, osm):
    save_home(signed_in)

    response = signed_in.get("/masjids/nearby")

    body = response.json()
    assert [m["name"] for m in body["masjids"]] == [
        "Kanata Muslim Association", "Stittsville Masjid", "Jamia Omar"
    ]
    distances = [m["distance_km"] for m in body["masjids"]]
    assert distances == sorted(distances)
    assert distances[0] == 1.1
    assert all(m["iqamah_status"] == "Iqamah times not added yet" for m in body["masjids"])
    assert body["radius_km"] == 15
    assert body["credit"] == "© OpenStreetMap contributors"


def test_nearby_needs_an_address_first(signed_in):
    response = signed_in.get("/masjids/nearby")
    assert response.status_code == 409


def test_picking_a_masjid_with_a_short_name(signed_in, osm):
    save_home(signed_in)
    kma = _nearby_ids(signed_in)["Kanata Muslim Association"]

    response = signed_in.put(
        "/settings/main-masjid", json={"choice": "masjid", "masjid_id": kma, "short_name": " KMA "}
    )

    settings = response.json()["settings"]
    assert settings["main_masjid_choice"] == "masjid"
    assert settings["main_masjid"]["name"] == "Kanata Muslim Association"
    assert settings["main_masjid"]["iqamah_status"] == "Iqamah times not added yet"
    assert settings["main_masjid_short_name"] == "KMA"


def test_typed_in_masjid_saves(signed_in, osm, db):
    save_home(signed_in)

    response = signed_in.put(
        "/settings/main-masjid",
        json={"choice": "custom", "name": "Barrhaven Musalla", "address": "3500 Fallowfield Rd"},
    )

    assert response.status_code == 200
    main = response.json()["settings"]["main_masjid"]
    assert (main["name"], main["address"], main["source"]) == (
        "Barrhaven Musalla", "3500 Fallowfield Rd", "user"
    )
    with DbSession(db) as session:
        masjid = session.scalars(select(Masjid).where(Masjid.source == "user")).one()
        # Nothing made up: no location and no OpenStreetMap ID.
        assert (masjid.latitude, masjid.osm_id) == (None, None)
    # It's listed as one of "yours" from now on.
    typed = signed_in.get("/masjids/nearby").json()["typed_by_you"]
    assert [m["name"] for m in typed] == ["Barrhaven Musalla"]


def test_typing_the_same_masjid_again_reuses_it(signed_in, db):
    body = {"choice": "custom", "name": "Barrhaven Musalla", "address": "3500 Fallowfield Rd"}
    signed_in.put("/settings/main-masjid", json=body)
    signed_in.put("/settings/main-masjid", json=body)

    with DbSession(db) as session:
        assert len(session.scalars(select(Masjid)).all()) == 1


def test_typed_in_masjid_needs_a_name_and_address(signed_in):
    response = signed_in.put("/settings/main-masjid", json={"choice": "custom", "name": "Only a name"})
    assert response.status_code == 422


def test_praying_at_home_skips_the_weekly_grid(signed_in, osm):
    save_home(signed_in)

    response = signed_in.put("/settings/main-masjid", json={"choice": "home"})

    settings = response.json()["settings"]
    assert settings["main_masjid_choice"] == "home"
    assert settings["main_masjid"] is None
    assert settings["missing"] == []  # no "weekly"


def test_made_up_masjid_id_is_refused(signed_in):
    response = signed_in.put(
        "/settings/main-masjid",
        json={"choice": "masjid", "masjid_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


# ---- Weekly grid ----


def test_weekly_grid_saves_all_7_days(signed_in, db):
    days = [
        {"weekday": d, "fajr": d == 4, "dhuhr": True, "asr": False, "maghrib": d >= 5, "isha": d % 2 == 0}
        for d in range(7)
    ]

    response = signed_in.put("/settings/weekly", json={"days": days})

    assert response.json()["settings"]["weekly"] == days
    with DbSession(db) as session:
        rows = session.scalars(select(WeeklyMasjidPrayers).order_by(WeeklyMasjidPrayers.weekday)).all()
    assert [r.weekday for r in rows] == list(range(7))
    assert [r.fajr for r in rows] == [False, False, False, False, True, False, False]
    assert [r.maghrib for r in rows] == [False, False, False, False, False, True, True]


def test_saving_the_grid_again_replaces_it(signed_in, db):
    signed_in.put("/settings/weekly", json={"days": [{"weekday": d, "dhuhr": True} for d in range(7)]})
    signed_in.put("/settings/weekly", json={"days": [{"weekday": d, "isha": True} for d in range(7)]})

    with DbSession(db) as session:
        rows = session.scalars(select(WeeklyMasjidPrayers)).all()
    assert len(rows) == 7
    assert all(r.isha and not r.dhuhr for r in rows)


@pytest.mark.parametrize(
    "weekdays", [[0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5, 5], [0, 1, 2, 3, 4, 5, 7]]
)
def test_weekly_grid_needs_each_day_once(signed_in, weekdays):
    response = signed_in.put("/settings/weekly", json={"days": [{"weekday": d} for d in weekdays]})
    assert response.status_code == 422


# ---- Jumuah ----


def test_more_than_one_jumuah_masjid(signed_in, osm):
    save_home(signed_in)
    ids = _nearby_ids(signed_in)

    response = signed_in.put(
        "/settings/jumuah", json={"masjid_ids": [ids["Stittsville Masjid"], ids["Jamia Omar"]]}
    )

    settings = response.json()["settings"]
    assert sorted(m["name"] for m in settings["jumuah_masjids"]) == ["Jamia Omar", "Stittsville Masjid"]
    assert settings["jumuah_saved"] is True


def test_no_jumuah_masjid_is_allowed(signed_in):
    response = signed_in.put("/settings/jumuah", json={"masjid_ids": []})
    assert response.json()["settings"]["jumuah_saved"] is True
    assert response.json()["settings"]["jumuah_masjids"] == []


# ---- Finishing ----


def test_finish_needs_every_answer(signed_in, osm):
    response = signed_in.post("/setup/finish")
    assert response.json()["detail"]["missing"] == ["address", "masjid", "weekly"]

    save_home(signed_in)
    response = signed_in.post("/setup/finish")

    assert response.status_code == 409
    assert response.json()["detail"]["missing"] == ["masjid", "weekly"]


def test_setup_is_only_3_questions(signed_in, osm, fake_google):
    # No methods step and no Jumuah step: defaults are used.
    response = setup_through_api(signed_in, osm)

    settings = response.json()["settings"]
    assert settings["setup_complete"] is True
    assert (settings["method"], settings["asr_method"]) == ("isna", "standard")
    assert settings["jumuah_masjids"] == []
    assert osm.photon_requests  # the location came from Photon
    events = fake_google.live_events(fake_google.calendars_of("user-a")[0].id)
    assert events[0]["description"].startswith("Calculated (ISNA, standard Asr)")


def test_full_setup_fills_the_calendar(signed_in, osm, fake_google):
    response = setup_through_api(signed_in, osm)

    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["setup_complete"] is True
    assert body["settings"]["missing"] == []
    assert body["calendar"]["status"] == "updated"
    assert body["calendar"]["sent"] == 70
    calendar = fake_google.calendars_of("user-a")[0]
    assert len(fake_google.live_events(calendar.id)) == 70
    assert signed_in.get("/me").json()["setup_complete"] is True


def test_setup_with_home_only(signed_in, osm, fake_google):
    response = setup_through_api(signed_in, osm, masjid=None)

    assert response.json()["calendar"]["sent"] == 70
    events = fake_google.live_events(fake_google.calendars_of("user-a")[0].id)
    assert all(e["summary"].endswith(" at home") for e in events)


def test_finishing_twice_adds_nothing(signed_in, osm, fake_google):
    setup_through_api(signed_in, osm)
    writes = len(fake_google.writes())

    again = signed_in.post("/setup/finish")

    assert again.json()["calendar"]["sent"] == 0
    assert len(fake_google.writes()) == writes


def test_change_after_setup_reports_a_dead_sign_in_instead_of_failing(signed_in, osm, fake_google):
    setup_through_api(signed_in, osm)
    fake_google.expire_access_tokens()
    fake_google.kill_refresh_tokens("user-a")

    response = signed_in.put("/settings/methods", json={"asr_method": "hanafi"})

    assert response.status_code == 200
    assert response.json()["settings"]["asr_method"] == "hanafi"  # still saved
    calendar = response.json()["calendar"]
    assert calendar["status"] == "sign_in_needed"
    assert calendar["waiting"] > 0
    assert signed_in.get("/me").json()["google_sign_in_needed"] is True


# ---- One user at a time ----


def test_settings_belong_to_one_user(fake_google, osm, set_today, db):
    set_today(DAY)
    with new_client() as alice, new_client() as bob:
        sign_in(alice, fake_google, sub="alice", email="alice@example.com")
        sign_in(bob, fake_google, sub="bob", email="bob@example.com")
        setup_through_api(alice, osm)
        alice.put(
            "/settings/main-masjid",
            json={"choice": "custom", "name": "Alice's Musalla", "address": "1 Private Rd"},
        )
        alice_masjid = alice.get("/settings").json()["main_masjid"]["id"]

        bob_settings = bob.get("/settings").json()
        assert bob_settings["address"] is None
        assert bob_settings["weekly"] == []
        assert bob_settings["jumuah_masjids"] == []
        assert bob_settings["setup_complete"] is False

        # Bob can't see or pick Alice's typed-in masjid.
        save_home(bob)
        assert bob.get("/masjids/nearby").json()["typed_by_you"] == []
        assert bob.put(
            "/settings/main-masjid", json={"choice": "masjid", "masjid_id": alice_masjid}
        ).status_code == 404
        assert bob.put("/settings/jumuah", json={"masjid_ids": [alice_masjid]}).status_code == 404

    with DbSession(db) as session:
        assert len(session.scalars(select(UserSettings)).all()) == 2
        assert {r.user_id for r in session.scalars(select(WeeklyMasjidPrayers))} == {
            session.scalars(select(UserSettings.user_id).where(UserSettings.setup_completed_at.isnot(None))).one()
        }
        assert session.scalars(select(UserJumuahMasjid)).all() == []  # not part of setup any more


def test_reading_settings_saves_nothing(signed_in, db):
    signed_in.get("/settings")
    with DbSession(db) as session:
        assert session.scalars(select(UserSettings)).all() == []


def test_settings_need_sign_in(client):
    assert client.get("/settings").status_code == 401
    assert client.put("/settings/methods", json={}).status_code == 401
    assert client.post("/setup/location/suggest", json={"query": HOME_QUERY}).status_code == 401
