"""The optional step (how early, short name, colours), Jumuah order, and
the update job each settings change queues."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MasjidSource, UpdateJob, UserSettings
from tests.calendar_helpers import fetch, google_events
from tests.conftest import sign_in
from tests.masjid_helpers import link, masjid_id, user_id
from tests.setup_helpers import pick_masjid, setup_through_api

TORONTO = ZoneInfo("America/Toronto")
DAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=TORONTO)


@pytest.fixture
def signed_in(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    return client


@pytest.fixture
def set_up(signed_in, fake_photon):
    response = setup_through_api(signed_in, fake_photon)
    assert response.status_code == 200
    return signed_in


def test_the_optional_step_saves_every_answer(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, finish=False)
    response = signed_in.put(
        "/settings/optional",
        json={"arrive_early_minutes": 5, "short_name": "KMA", "prayer_color_id": "7", "drive_color_id": "11"},
    )
    settings = response.json()["settings"]
    assert settings["missing"] == []
    assert (settings["arrive_early_minutes"], settings["prayer_color_id"], settings["drive_color_id"]) == (5, "7", "11")
    assert settings["main_masjid_short_name"] == "KMA"


def test_skipping_uses_the_defaults(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, finish=False)
    settings = signed_in.put("/settings/optional", json={}).json()["settings"]
    assert settings["missing"] == []
    # 5 minutes early, and Basil (Google's green, ID "10") for both.
    assert (settings["arrive_early_minutes"], settings["prayer_color_id"], settings["drive_color_id"]) == (5, "10", "10")
    assert settings["main_masjid_short_name"] is None


def test_calendar_colour_can_still_be_picked(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, finish=False)
    body = {"arrive_early_minutes": 0, "prayer_color_id": None, "drive_color_id": None}
    settings = signed_in.put("/settings/optional", json=body).json()["settings"]
    assert (settings["arrive_early_minutes"], settings["prayer_color_id"], settings["drive_color_id"]) == (0, None, None)


def test_existing_answers_arent_changed_by_the_new_defaults(set_up, db):
    # Saved before the defaults changed: 0 minutes and the calendar's colour.
    with Session(db) as session:
        row = session.scalars(select(UserSettings)).one()
        row.arrive_early_minutes, row.prayer_color_id, row.drive_color_id = 0, None, None
        session.commit()
    settings = set_up.get("/settings").json()
    assert (settings["arrive_early_minutes"], settings["prayer_color_id"], settings["drive_color_id"]) == (0, None, None)


@pytest.mark.parametrize(
    "body",
    [
        {"arrive_early_minutes": 61},
        {"arrive_early_minutes": -1},
        {"arrive_early_minutes": 2.5},
        {"arrive_early_minutes": 5.0},
        {"arrive_early_minutes": "5"},
        {"arrive_early_minutes": None},
        {"prayer_color_id": "12"},
        {"drive_color_id": "0"},
        {"prayer_color_id": "red"},
        {"short_name": "x" * 41},
    ],
)
def test_bad_answers_are_refused(signed_in, fake_photon, body):
    setup_through_api(signed_in, fake_photon, finish=False)
    assert signed_in.put("/settings/optional", json=body).status_code == 422


def test_a_short_name_needs_a_masjid(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, masjid=None, finish=False)
    settings = signed_in.put("/settings/optional", json={"short_name": "KMA"}).json()["settings"]
    assert settings["main_masjid_short_name"] is None


def test_picking_the_same_masjid_keeps_the_short_name(set_up):
    masjid = set_up.get("/settings").json()["main_masjid"]
    response = set_up.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": masjid["id"]})
    assert response.json()["settings"]["main_masjid_short_name"] == "KMA"
    other = pick_masjid(set_up, "Stittsville", "Stittsville Masjid")
    response = set_up.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": other["id"]})
    assert response.json()["settings"]["main_masjid_short_name"] is None


def test_each_change_queues_one_update_job_with_a_stable_id(set_up, db):
    for minutes in (5, 10, 10):
        response = set_up.put("/settings/optional", json={"arrive_early_minutes": minutes, "short_name": "KMA"})
        assert response.json()["calendar"]["status"] == "updated"
    with Session(db) as session:
        jobs = session.scalars(select(UpdateJob)).all()
    assert [j.id for j in jobs] == [f"update:{user_id(db, 'user-a')}"]
    assert jobs[0].status == "done"
    assert jobs[0].reason == "settings"


def test_changing_how_early_sends_only_drive_blocks(set_up, db, fake_google, ors_key):
    set_up.post("/calendar/sync")  # drive times on now, so drive blocks are added
    before = len(fake_google.writes())
    response = set_up.put("/settings/optional", json={"arrive_early_minutes": 15, "short_name": "KMA"})
    changed = fake_google.writes()[before:]
    assert response.json()["calendar"]["sent"] == len(changed) > 0
    assert {w.body["summary"] for w in changed} == {"Drive to KMA"}


def test_changing_the_prayer_colour_sends_only_prayer_blocks(set_up, fake_google, ors_key):
    set_up.post("/calendar/sync")
    before = len(fake_google.writes())
    set_up.put("/settings/optional", json={"prayer_color_id": "3", "short_name": "KMA"})
    changed = fake_google.writes()[before:]
    assert changed and all(w.body["colorId"] == "3" for w in changed)
    assert not any(w.body["summary"].startswith("Drive") for w in changed)


def test_changing_the_short_name_renames_the_events(set_up, fake_google):
    set_up.put("/settings/optional", json={"short_name": "Kanata"})
    titles = {e["summary"] for e in google_events(fake_google)}
    assert "Isha at Kanata" in titles and "Isha at KMA" not in titles


def test_a_save_while_an_update_runs_says_its_waiting(set_up, db):
    with Session(db) as session:
        job = session.get(UpdateJob, f"update:{user_id(db, 'user-a')}")
        job.status, job.started_at = "running", NOW
        session.commit()
    response = set_up.put("/settings/optional", json={"arrive_early_minutes": 5, "short_name": "KMA"})
    assert response.json()["calendar"]["status"] == "waiting"
    assert "already updating" in response.json()["calendar"]["message"]


def test_the_masjid_shows_where_its_times_come_from(set_up, db, http, fake_mawaqit, set_today):
    kma = masjid_id(db, "Kanata Muslim Association")
    link(db, kma, "kma-kanata", fake_mawaqit)
    assert set_up.get("/settings").json()["main_masjid"]["iqamah_status"] == "Linked to MAWAQIT. Its times haven't been read yet"
    fetch(db, http, NOW - timedelta(days=2))
    assert set_up.get("/settings").json()["main_masjid"]["iqamah_status"] == (
        "MAWAQIT times couldn't be confirmed since Oct 22, 2026, so calculated times are used"
    )
    # Read again 2 days later, the page now covers Friday Oct 30's Jumuah, which is a change.
    fetch(db, http, NOW)
    assert set_up.get("/settings").json()["main_masjid"]["iqamah_status"] == "Times from MAWAQIT, updated Oct 24, 2026"


def test_a_notice_shows_when_masjid_times_cant_be_confirmed(set_up, db, http, fake_mawaqit, set_today):
    kma = masjid_id(db, "Kanata Muslim Association")
    link(db, kma, "kma-kanata", fake_mawaqit, at=NOW - timedelta(days=3))
    # Linked, never read, but under 24 hours since nothing could be read: no notice yet.
    with Session(db) as session:
        session.get(MasjidSource, kma).linked_at = NOW - timedelta(hours=2)
        session.commit()
    assert set_up.get("/settings").json()["masjid_notices"] == []

    fetch(db, http, NOW - timedelta(hours=23))
    assert set_up.get("/settings").json()["masjid_notices"] == []

    with Session(db) as session:
        session.get(MasjidSource, kma).last_success_at = NOW - timedelta(days=2)
        session.commit()
    assert set_up.get("/settings").json()["masjid_notices"] == [
        "KMA's times couldn't be confirmed since Oct 22, 2026. Your calendar is using calculated times until they're back."
    ]


def test_a_masjid_never_read_for_a_day_gets_a_notice_from_when_it_was_linked(set_up, db, fake_mawaqit, set_today):
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit, at=NOW - timedelta(days=3))
    assert set_up.get("/settings").json()["masjid_notices"] == [
        "KMA's times couldn't be confirmed since Oct 21, 2026. Your calendar is using calculated times until they're back."
    ]


def test_nothing_reaches_google_until_setup_finishes(signed_in, fake_photon, fake_google):
    # Every question, including the optional step, but not finished yet.
    setup_through_api(signed_in, fake_photon, finish=False)
    assert [r for r in fake_google.requests if "/calendar/" in r.path] == []
    assert fake_google.calendars == {}
    # Changing an answer before finishing doesn't write either.
    signed_in.put("/settings/optional", json={"arrive_early_minutes": 10})
    assert fake_google.requests == []

    # Finishing is the first calendar update: the calendar is made and filled.
    response = signed_in.post("/setup/finish")
    assert response.json()["calendar"]["status"] == "updated"
    assert fake_google.writes()
    assert all(e.get("colorId") == "10" for e in google_events(fake_google))


def test_finish_is_refused_before_the_optional_step(signed_in, fake_photon, fake_google, db):
    setup_through_api(signed_in, fake_photon, finish=False)
    with Session(db) as session:
        session.scalars(select(UserSettings)).one().optional_saved = False
        session.commit()
    response = signed_in.post("/setup/finish")
    assert response.status_code == 409
    assert response.json()["detail"]["missing"] == ["optional"]
    assert fake_google.requests == []


@pytest.mark.parametrize("minutes", [0, 31, 60])
def test_how_early_takes_0_to_60(signed_in, fake_photon, minutes):
    setup_through_api(signed_in, fake_photon, finish=False)
    response = signed_in.put("/settings/optional", json={"arrive_early_minutes": minutes})
    assert response.status_code == 200
    assert response.json()["settings"]["arrive_early_minutes"] == minutes
