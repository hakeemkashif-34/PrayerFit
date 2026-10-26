"""Tests for the setup questions and the settings endpoints.

Google and Photon are both faked.
"""

import logging
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.models import Masjid, UserSettings, WeeklyMasjidPrayers
from tests.conftest import new_client, sign_in
from tests.setup_helpers import (
    HOME,
    HOME_PLACE,
    HOME_QUERY,
    add_home,
    add_masjids,
    pick_masjid,
    setup_through_api,
)

DAY = date(2026, 10, 24)  # a Saturday


@pytest.fixture
def signed_in(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    return client


@pytest.fixture
def osm(fake_photon):
    """The fake Photon, with the home and some masjids on it."""
    add_home(fake_photon)
    add_masjids(fake_photon)
    return fake_photon


def save_home(client) -> None:
    """Type the address and pick the Canadian suggestion, like the website does."""
    suggestions = client.post("/setup/location/suggest", json={"query": HOME_QUERY}).json()["suggestions"]
    index = next(s["index"] for s in suggestions if s["label"] == HOME_PLACE)
    response = client.put("/settings/location", json={"query": HOME_QUERY, "index": index})
    assert response.status_code == 200


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
    assert osm.requests == []


def test_picking_a_suggestion_saves_it_without_a_second_lookup(signed_in, osm):
    signed_in.post("/setup/location/suggest", json={"query": HOME_QUERY})
    response = signed_in.put("/settings/location", json={"query": HOME_QUERY, "index": 0})

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["address"] == HOME_PLACE
    assert settings["place_name"] == HOME_PLACE
    assert settings["time_zone"] == "America/Toronto"
    assert settings["missing"] == ["masjid", "weekly", "optional"]
    assert len(osm.requests) == 1  # picking used the cached answer
    assert response.json()["calendar"] is None  # nothing goes to Google during setup


def test_the_saved_address_has_no_postal_code(signed_in, osm, db):
    save_home(signed_in)

    settings = signed_in.get("/settings").json()
    assert "K2T" not in settings["address"]
    assert "K2T" not in settings["place_name"]


def test_picking_a_place_not_in_the_list_is_refused(signed_in, osm):
    response = signed_in.put("/settings/location", json={"query": HOME_QUERY, "index": 4})
    assert response.status_code == 404


def test_time_zone_comes_from_the_location(signed_in, fake_photon):
    fake_photon.add_place(49.2827, -123.1207, name="Robson Street", city="Vancouver", country="Canada")

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


def test_busy_photon_is_a_503_with_a_message(signed_in, fake_photon):
    fake_photon.failure = 429

    response = signed_in.post("/setup/location/suggest", json={"query": HOME_QUERY})

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "The search is busy. Try again in a minute."


# ---- Methods ----


def test_there_is_no_method_setting(signed_in):
    # Calculated times always use ISNA with standard Asr.
    settings = signed_in.get("/settings").json()
    assert "method" not in settings and "asr_method" not in settings
    assert signed_in.put("/settings/methods", json={"method": "mwl"}).status_code in (404, 405)


# ---- Main masjid ----


def test_masjid_suggestions_show_name_and_distance_closest_first(signed_in, osm):
    save_home(signed_in)

    response = signed_in.post("/setup/masjid/suggest", json={"query": "Kanata"})

    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    # The one in Kanata. The Toronto one with a similar name is over 100 km away, so it's left out.
    assert [s["label"] for s in suggestions] == ["Kanata Muslim Association"]
    assert suggestions[0] == {
        "index": 0, "kind": "masjid", "label": "Kanata Muslim Association",
        "detail": "351 Sandhill Road, Ottawa", "distance_km": 1.1,
    }
    # Suggesting saves nothing.
    assert signed_in.get("/settings").json()["main_masjid_choice"] is None


def test_masjid_suggestions_need_a_saved_location(signed_in, osm):
    response = signed_in.post("/setup/masjid/suggest", json={"query": "Kanata"})
    assert response.status_code == 409
    assert osm.requests == []


def test_picking_a_masjid_with_a_short_name(signed_in, osm, db):
    save_home(signed_in)
    picked = pick_masjid(signed_in, "Kanata Muslim", "Kanata Muslim Association")

    response = signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": picked["id"]})
    settings = response.json()["settings"]
    assert settings["main_masjid_choice"] == "masjid"
    assert settings["main_masjid"]["name"] == "Kanata Muslim Association"
    assert settings["main_masjid"]["distance_km"] == 1.1
    assert settings["main_masjid"]["iqamah_status"] == "Not linked to MAWAQIT, so calculated times are used"
    assert settings["main_masjid_short_name"] is None

    # The short name is part of the optional step now.
    response = signed_in.put("/settings/optional", json={"short_name": " KMA "})
    settings = response.json()["settings"]
    assert settings["main_masjid_short_name"] == "KMA"
    with DbSession(db) as session:
        masjid = session.scalars(select(Masjid)).one()
        assert (masjid.source, masjid.osm_type, masjid.osm_id) == ("openstreetmap", "node", 101)
        assert masjid.address == "351 Sandhill Road, Ottawa"


def test_picking_the_same_masjid_twice_saves_it_once(signed_in, osm, db):
    save_home(signed_in)
    first = pick_masjid(signed_in, "Kanata Muslim", "Kanata Muslim Association")
    second = pick_masjid(signed_in, "Kanata", "Kanata Muslim Association")

    assert first["id"] == second["id"]
    with DbSession(db) as session:
        assert len(session.scalars(select(Masjid)).all()) == 1


def test_a_masjid_not_on_the_map_can_be_picked_by_its_address(signed_in, osm, db):
    osm.add_place(HOME[0] + 0.05, HOME[1], housenumber="3500", street="Fallowfield Road", city="Ottawa", country="Canada")
    save_home(signed_in)

    suggestions = signed_in.post("/setup/masjid/suggest", json={"query": "3500 Fallowfield"}).json()["suggestions"]
    assert [(s["kind"], s["label"]) for s in suggestions] == [("address", "3500 Fallowfield Road, Ottawa, Canada")]
    picked = pick_masjid(signed_in, "3500 Fallowfield", "3500 Fallowfield Road, Ottawa, Canada")

    # Nothing made up: no name, just the address the user picked.
    assert (picked["name"], picked["address"], picked["source"]) == (None, "3500 Fallowfield Road, Ottawa, Canada", "user")
    signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": picked["id"]})
    response = signed_in.put("/settings/optional", json={"short_name": "Barrhaven Musalla"})
    assert response.json()["settings"]["main_masjid_short_name"] == "Barrhaven Musalla"
    with DbSession(db) as session:
        masjid = session.scalars(select(Masjid)).one()
        assert masjid.osm_id is None
        assert masjid.created_by_user_id is not None


def test_picking_a_masjid_not_in_the_list_is_refused(signed_in, osm):
    save_home(signed_in)
    response = signed_in.post("/masjids/from-suggestion", json={"query": "Kanata", "index": 4})
    assert response.status_code == 404


def test_skip_means_every_prayer_at_home_and_no_weekly_grid(signed_in, osm):
    save_home(signed_in)

    response = signed_in.put("/settings/main-masjid", json={"choice": "home"})

    settings = response.json()["settings"]
    assert settings["main_masjid_choice"] == "home"
    assert settings["main_masjid"] is None
    assert settings["missing"] == ["optional"]  # no "weekly"


def test_made_up_masjid_id_is_refused(signed_in):
    response = signed_in.put(
        "/settings/main-masjid",
        json={"choice": "masjid", "masjid_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


def test_the_old_typed_in_choice_is_gone(signed_in):
    response = signed_in.put("/settings/main-masjid", json={"choice": "custom", "name": "A", "address": "B"})
    assert response.status_code == 422


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


def test_ticking_nothing_means_every_prayer_at_home(signed_in, osm, fake_google):
    response = setup_through_api(signed_in, osm, at_masjid={})

    assert response.json()["settings"]["setup_complete"] is True
    assert all(not any(d[p] for p in ("fajr", "dhuhr", "asr", "maghrib", "isha")) for d in response.json()["settings"]["weekly"])
    events = fake_google.live_events(fake_google.calendars_of("user-a")[0].id)
    assert len(events) == 70
    assert {e["summary"] for e in events} == {"Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"}


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


def test_jumuah_is_at_the_main_masjid_with_its_1st_jumuah_picked(signed_in, osm):
    save_home(signed_in)
    kma = pick_masjid(signed_in, "Kanata", "Kanata Muslim Association")
    response = signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": kma["id"]})
    settings = response.json()["settings"]
    assert settings["jumuah_pick"] == {"masjid_id": kma["id"], "order": 1}
    assert "jumuah_masjids" not in settings and "jumuah_saved" not in settings


# ---- Finishing ----


def test_finish_needs_every_answer(signed_in, osm):
    response = signed_in.post("/setup/finish")
    assert response.json()["detail"]["missing"] == ["address", "masjid", "weekly", "optional"]

    save_home(signed_in)
    response = signed_in.post("/setup/finish")

    assert response.status_code == 409
    assert response.json()["detail"]["missing"] == ["masjid", "weekly", "optional"]


def test_setup_is_4_questions(signed_in, osm, fake_google):
    # No Jumuah step: Jumuah is always at the main masjid.
    response = setup_through_api(signed_in, osm)

    settings = response.json()["settings"]
    assert settings["setup_complete"] is True
    assert settings["jumuah_pick"] == {"masjid_id": settings["main_masjid"]["id"], "order": 1}
    assert osm.requests  # the location came from Photon
    events = fake_google.live_events(fake_google.calendars_of("user-a")[0].id)
    assert not any("description" in e for e in events)


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
    assert {e["summary"] for e in events} == {"Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"}


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

    response = signed_in.put("/settings/optional", json={"short_name": "Kanata"})

    assert response.status_code == 200
    assert response.json()["settings"]["main_masjid_short_name"] == "Kanata"  # still saved
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
        osm.add_place(HOME[0] + 0.05, HOME[1], housenumber="1", street="Private Road", city="Ottawa")
        setup_through_api(alice, osm)
        # Alice picks a masjid by its address, so it's hers only.
        alice_masjid = pick_masjid(alice, "1 Private", "1 Private Road, Ottawa")["id"]

        bob_settings = bob.get("/settings").json()
        assert bob_settings["address"] is None
        assert bob_settings["weekly"] == []
        assert bob_settings["jumuah_pick"] is None
        assert bob_settings["setup_complete"] is False

        # Bob can't pick Alice's masjid.
        save_home(bob)
        assert bob.put(
            "/settings/main-masjid", json={"choice": "masjid", "masjid_id": alice_masjid}
        ).status_code == 404

    with DbSession(db) as session:
        assert len(session.scalars(select(UserSettings)).all()) == 2
        assert {r.user_id for r in session.scalars(select(WeeklyMasjidPrayers))} == {
            session.scalars(select(UserSettings.user_id).where(UserSettings.setup_completed_at.isnot(None))).one()
        }
        # Only Alice has a Jumuah pick, at her main masjid. Nothing for Bob.
        picks = {(r.main_masjid_id, r.jumuah_pick_masjid_id) for r in session.scalars(select(UserSettings))}
        assert len([p for p in picks if p[1] is not None]) == 1
        assert all(main == pick for main, pick in picks if pick is not None)


def test_reading_settings_saves_nothing(signed_in, db):
    signed_in.get("/settings")
    with DbSession(db) as session:
        assert session.scalars(select(UserSettings)).all() == []


def test_settings_need_sign_in(client):
    assert client.get("/settings").status_code == 401
    assert client.put("/settings/optional", json={}).status_code == 401
    assert client.post("/setup/location/suggest", json={"query": HOME_QUERY}).status_code == 401
