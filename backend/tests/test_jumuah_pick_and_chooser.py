"""The Jumuah pick and the Jumuah chooser's data.

The made-up MAWAQIT page has Jumuah at 13:30 (1st) and 14:30 (2nd).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from tests.calendar_helpers import clock, fetch, google_events, titled
from tests.conftest import sign_in
from tests.fake_google import OLD_SCOPES
from tests.masjid_helpers import link, masjid_id
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


def choices(client, **body) -> dict:
    response = client.post("/jumuah/choices", json=body)
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
    assert first["drive_minutes"] == 14
    assert "commute_minutes" not in first and "commute_source" not in first
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


def test_an_unsaved_how_early_changes_the_windows_but_saves_nothing(with_times, ors_key):
    first = choices(with_times, jumuah_arrive_early_minutes=20)["slots"][0]
    # 1:30, 20 minutes early, and the 14 minute drive: leave 12:56.
    assert (local(first["leave_at"]), local(first["arrive_at"])) == ("12:56", "13:10")
    assert with_times.get("/settings").json()["jumuah_arrive_early_minutes"] == 5


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
