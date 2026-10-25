"""The user's own commute times, the Jumuah pick, and the Jumuah chooser's data.

The made-up MAWAQIT page has Jumuah at 13:30 (1st) and 14:30 (2nd).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserCommuteTime
from tests.calendar_helpers import clock, fetch, google_events, on, titled
from tests.conftest import sign_in
from tests.fake_google import OLD_SCOPES
from tests.masjid_helpers import link, masjid_id
from tests.setup_helpers import pick_masjid, setup_through_api

TORONTO = ZoneInfo("America/Toronto")
DAY = date(2026, 10, 25)  # Sunday
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=TORONTO)
FRIDAY = date(2026, 10, 30)
MONDAY = date(2026, 10, 26)
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


def choices(client, **body) -> dict:
    response = client.post("/jumuah/choices", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def local(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(TORONTO).strftime("%H:%M")


# ---- Commute times ----


def test_commute_times_list_the_main_and_jumuah_masjids(set_up, kma):
    other = pick_masjid(set_up, "Stittsville", "Stittsville Masjid")
    set_up.put("/settings/jumuah", json={"masjid_ids": [kma, other["id"]]})
    times = set_up.get("/settings").json()["commute_times"]
    # KMA is both, so it's listed once.
    assert [(t["masjid_name"], t["minutes"]) for t in times] == [
        ("Kanata Muslim Association", None), ("Stittsville Masjid", None),
    ]


def test_your_own_commute_time_is_used_and_ors_isnt_asked(set_up, kma, fake_google, fake_ors, ors_key):
    response = set_up.put("/settings/commute-times", json={"times": [{"masjid_id": kma, "minutes": 10}]})
    assert response.status_code == 200
    assert response.json()["settings"]["commute_times"][0]["minutes"] == 10
    assert fake_ors.requests == []
    commute = on(google_events(fake_google), MONDAY)[1]
    assert commute["summary"] == "Commute to KMA"
    assert commute["description"].startswith("10 min commute (your time).")
    # Isha at KMA is at 19:22 (calculated). 5 minutes early and a 10 minute commute: leave 19:07.
    assert clock(titled(google_events(fake_google), MONDAY, "Isha at KMA")) == "19:22"
    later = [e for e in on(google_events(fake_google), MONDAY) if e["summary"] == "Commute to KMA"][-1]
    assert (clock(later), clock(later, end=True)) == ("19:07", "19:17")


def test_clearing_a_commute_time_goes_back_to_ors(set_up, kma, fake_google, fake_ors, ors_key):
    set_up.put("/settings/commute-times", json={"times": [{"masjid_id": kma, "minutes": 10}]})
    response = set_up.put("/settings/commute-times", json={"times": [{"masjid_id": kma, "minutes": None}]})
    assert response.json()["settings"]["commute_times"][0]["minutes"] is None
    assert len(fake_ors.requests) == 1
    commute = on(google_events(fake_google), MONDAY)[1]
    assert commute["description"].startswith("14 min commute (driving estimate from OpenRouteService, no live traffic).")


@pytest.mark.parametrize("minutes", [0, 121, 2.5, "10", True])
def test_commute_times_are_whole_minutes_from_1_to_120(set_up, kma, minutes):
    response = set_up.put("/settings/commute-times", json={"times": [{"masjid_id": kma, "minutes": minutes}]})
    assert response.status_code == 422


def test_a_masjid_that_isnt_yours_is_refused(set_up, db):
    other = pick_masjid(set_up, "Jamia Omar", "Jamia Omar")
    response = set_up.put("/settings/commute-times", json={"times": [{"masjid_id": other["id"], "minutes": 10}]})
    assert response.status_code == 404
    with Session(db) as session:
        assert session.scalars(select(UserCommuteTime)).all() == []


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
    # KMA isn't linked to MAWAQIT, so the setup page skips the chooser.
    data = choices(set_up)
    assert (data["friday"], data["slots"], data["selected"]) == ("2026-10-30", [], None)


def test_the_chooser_shows_every_slot_and_its_window(with_times, kma, ors_key):
    data = choices(with_times)
    assert data["busy_checked"] is True and data["busy"] == []
    first, second = data["slots"]
    assert (first["order_label"], local(first["starts_at"]), second["order_label"]) == ("1st Jumuah", "13:30", "2nd Jumuah")
    # 5 minutes early, a 14 minute driving estimate, and 45 minutes (estimated).
    assert (local(first["leave_at"]), local(first["arrive_at"]), local(first["ends_at"])) == ("13:11", "13:25", "14:15")
    assert (first["commute_minutes"], first["commute_source"]) == (14, "ors")
    assert (first["jumuah_minutes"], first["length_estimated"], first["fits"]) == (45, True, True)
    assert data["selected"] == {"masjid_id": kma, "order": 1}


def test_busy_slots_are_grey_and_the_earliest_that_fits_is_selected(with_times, kma, fake_google):
    fake_google.busy["user-a"] = BUSY_1_TO_1_40
    data = choices(with_times)
    assert [s["fits"] for s in data["slots"]] == [False, True]
    assert [(local(b["starts_at"]), local(b["ends_at"])) for b in data["busy"]] == [("13:00", "13:40")]
    assert data["selected"] == {"masjid_id": kma, "order": 2}


def test_a_saved_pick_is_selected_even_when_it_clashes(with_times, kma, fake_google):
    with_times.put("/settings/jumuah-pick", json={"masjid_id": kma, "order": 1})
    fake_google.busy["user-a"] = BUSY_1_TO_1_40
    assert choices(with_times)["selected"] == {"masjid_id": kma, "order": 1}


def test_unsaved_answers_change_the_windows_but_save_nothing(with_times, kma, db, ors_key):
    data = choices(with_times, jumuah_arrive_early_minutes=20, commute_minutes={kma: 30})
    first = data["slots"][0]
    assert (local(first["leave_at"]), local(first["arrive_at"])) == ("12:40", "13:10")
    assert (first["commute_minutes"], first["commute_source"]) == (30, "user")
    settings = with_times.get("/settings").json()
    assert settings["jumuah_arrive_early_minutes"] == 5
    assert settings["commute_times"][0]["minutes"] is None


def test_a_saved_commute_time_can_be_cleared_on_the_page(with_times, kma, ors_key):
    with_times.put("/settings/commute-times", json={"times": [{"masjid_id": kma, "minutes": 30}]})
    first = choices(with_times, commute_minutes={kma: None})["slots"][0]
    assert (first["commute_minutes"], first["commute_source"]) == (14, "ors")


@pytest.mark.parametrize("minutes", [0, 121, True])
def test_bad_unsaved_commute_times_are_refused(with_times, kma, minutes):
    assert with_times.post("/jumuah/choices", json={"commute_minutes": {kma: minutes}}).status_code == 422


@pytest.mark.parametrize("minutes", [-1, 61, 2.5])
def test_a_bad_unsaved_how_early_is_refused(with_times, minutes):
    assert with_times.post("/jumuah/choices", json={"jumuah_arrive_early_minutes": minutes}).status_code == 422


def test_without_free_busy_access_busy_isnt_checked(client, fake_google, fake_photon, set_today, db, http, fake_mawaqit):
    sign_in(client, fake_google, scopes=OLD_SCOPES)
    set_today(DAY)
    setup_through_api(client, fake_photon)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    fake_google.busy["user-a"] = BUSY_1_TO_1_40
    data = choices(client)
    assert (data["busy_checked"], data["busy"]) == (False, [])
    assert all(s["fits"] for s in data["slots"])
    assert fake_google.freebusy_requests() == []
    assert client.get("/me").json()["busy_access"] is False


def test_the_chooser_needs_sign_in(client):
    assert client.post("/jumuah/choices", json={}).status_code == 401
