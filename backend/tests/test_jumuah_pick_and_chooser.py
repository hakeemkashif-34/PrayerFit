"""The Jumuah pick and the Jumuah chooser's data.

The made-up MAWAQIT page has Jumuah at 13:30 (1st) and 14:30 (2nd).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import uuid

import pytest
from sqlalchemy.orm import Session

from app.masjid_times.scheduler import run_fetch
from app.models import Masjid
from tests.calendar_helpers import clock, fetch, google_events, titled
from tests.conftest import sign_in
from tests.masjid_helpers import link, masjid_id
from tests.mawaqit_pages import conf
from tests.setup_helpers import pick_masjid, setup_through_api

TORONTO = ZoneInfo("America/Toronto")
DAY = date(2026, 10, 25)  # Sunday
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=TORONTO)
FRIDAY = date(2026, 10, 30)
BUSY_1_TO_1_40 = [("2026-10-30T17:00:00Z", "2026-10-30T17:40:00Z")]


@pytest.fixture
def signed_in(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    return client


@pytest.fixture
def set_up(signed_in, fake_photon):
    assert setup_through_api(signed_in, fake_photon).status_code == 200
    return signed_in


@pytest.fixture
def kma(db):
    return str(masjid_id(db, "Kanata Muslim Association"))


@pytest.fixture
def with_times(set_up, db, http, fake_mawaqit, kma):
    """KMA linked to MAWAQIT and read, so it has this Friday's Jumuah times."""
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    return set_up


def choices(client, masjid_ids: list[str] | None = None) -> dict:
    response = client.get("/jumuah/slots", params={"masjid_id": masjid_ids or []})
    assert response.status_code == 200, response.text
    return response.json()


def local(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(TORONTO).strftime("%H:%M")


# ---- Drive times only come from OpenRouteService ----


def test_there_is_no_commute_time_setting(set_up, kma):
    assert set_up.put("/settings/commute-times", json={"times": [{"masjid_id": kma, "minutes": 10}]}).status_code == 404
    assert "commute_times" not in set_up.get("/settings").json()


# ---- The Jumuah pick ----


def test_saving_and_clearing_the_pick(with_times, kma, fake_google):
    response = with_times.put("/settings/jumuah-pick", json={"masjid_id": kma, "order": 2})
    assert response.json()["settings"]["jumuah_pick"] == {"masjid_id": kma, "order": 2}
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "14:30"
    response = with_times.put("/settings/jumuah-pick", json={})
    assert response.json()["settings"]["jumuah_pick"] is None
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "13:30"


@pytest.mark.parametrize("order", [0, 4, "1", 1.0])
def test_a_slot_is_1_2_or_3(set_up, kma, order):
    assert set_up.put("/settings/jumuah-pick", json={"masjid_id": kma, "order": order}).status_code == 422


def test_a_pick_needs_both_a_masjid_and_a_slot(set_up, kma):
    assert set_up.put("/settings/jumuah-pick", json={"order": 1}).status_code == 422
    assert set_up.put("/settings/jumuah-pick", json={"masjid_id": kma}).status_code == 422


def test_removing_the_picked_masjid_clears_the_pick(with_times, kma):
    other = pick_masjid(with_times, "Stittsville", "Stittsville Masjid")
    with_times.put("/settings/jumuah", json={"masjid_ids": [kma, other["id"]]})
    with_times.put("/settings/jumuah-pick", json={"masjid_id": other["id"], "order": 1})
    response = with_times.put("/settings/jumuah", json={"masjid_ids": [kma]})
    assert response.json()["settings"]["jumuah_pick"] is None
    # Keeping the picked masjid keeps the pick.
    with_times.put("/settings/jumuah-pick", json={"masjid_id": kma, "order": 2})
    other = pick_masjid(with_times, "Jamia Omar", "Jamia Omar")
    response = with_times.put("/settings/jumuah", json={"masjid_ids": [other["id"], kma]})
    assert response.json()["settings"]["jumuah_pick"] == {"masjid_id": kma, "order": 2}


def test_the_pick_must_be_a_jumuah_masjid(set_up):
    other = pick_masjid(set_up, "Jamia Omar", "Jamia Omar")
    assert set_up.put("/settings/jumuah-pick", json={"masjid_id": other["id"], "order": 1}).status_code == 404


# ---- The chooser ----


def test_no_jumuah_times_means_no_slots(set_up):
    # KMA isn't linked to MAWAQIT, so setup skips the question.
    data = choices(set_up)
    assert (data["slots"], data["selected"]) == ([], None)


def test_each_slot_runs_from_its_start_for_the_jumuah_length(with_times, db, kma):
    data = choices(with_times)
    first, second = data["slots"]
    assert (first["masjid_label"], first["order_label"], second["order_label"]) == ("KMA", "1st Jumuah", "2nd Jumuah")
    # This week's times as the example, and 45 minutes since KMA's length isn't set.
    assert [(local(s["starts_at"]), local(s["ends_at"])) for s in data["slots"]] == [("13:30", "14:15"), ("14:30", "15:15")]
    assert (first["jumuah_minutes"], first["length_estimated"]) == (45, True)
    # Nothing about a Friday, the drive, or the user's calendar.
    assert not {"friday", "busy", "busy_checked"} & set(data)
    assert not {"leave_at", "drive_minutes", "fits"} & set(first)
    # The 1st Jumuah is pre-selected.
    assert data["selected"] == {"masjid_id": kma, "order": 1}

    with Session(db) as session:
        session.get(Masjid, uuid.UUID(kma)).jumuah_minutes = 40
        session.commit()
    first = choices(with_times)["slots"][0]
    assert (local(first["ends_at"]), first["length_estimated"]) == ("14:10", False)


def test_busy_times_and_drive_times_are_never_asked(with_times, fake_google, fake_ors, ors_key):
    fake_google.busy["user-a"] = BUSY_1_TO_1_40
    google_calls, ors_calls = len(fake_google.requests), len(fake_ors.requests)
    data = choices(with_times)
    assert len(data["slots"]) == 2
    assert (len(fake_google.requests), len(fake_ors.requests)) == (google_calls, ors_calls)


def test_a_saved_pick_is_selected(with_times, kma):
    with_times.put("/settings/jumuah-pick", json={"masjid_id": kma, "order": 2})
    assert choices(with_times)["selected"] == {"masjid_id": kma, "order": 2}


def test_setup_can_ask_about_a_masjid_it_hasnt_saved_yet(with_times, db, http, fake_mawaqit, kma):
    # Picked on the Required page, but not saved until Next. Its page has a 1st Jumuah at 1:15 only.
    other = pick_masjid(with_times, "Stittsville", "Stittsville Masjid")
    link(db, uuid.UUID(other["id"]), "stittsville", fake_mawaqit, conf(jumua="13:15", jumua2=None))
    with Session(db) as session:
        run_fetch(session, http, uuid.UUID(other["id"]), NOW, force=True)

    data = choices(with_times, [other["id"]])
    assert [(s["masjid_label"], s["order_label"], local(s["starts_at"])) for s in data["slots"]] == [
        ("Stittsville Masjid", "1st Jumuah", "13:15"),
    ]
    assert data["selected"] == {"masjid_id": other["id"], "order": 1}
    # Nothing was saved: KMA is still the main masjid and the only Jumuah masjid.
    settings = with_times.get("/settings").json()
    assert [m["id"] for m in settings["jumuah_masjids"]] == [kma]


def test_a_masjid_that_cant_be_picked_is_refused(set_up):
    assert set_up.get("/jumuah/slots", params={"masjid_id": str(uuid.uuid4())}).status_code == 404


def test_the_chooser_needs_sign_in(client):
    assert client.get("/jumuah/slots").status_code == 401
