"""Busy times from Google's free/busy, and how they move Jumuah.

Only the primary calendar is read. The fake also answers for the Prayers
calendar (busy all day), which the app must ignore.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.busy_times import busy_between
from app.models import GoogleToken, UserSettings
from tests.calendar_helpers import clock, fetch, google_events, on, refresh, titled
from tests.fake_google import OLD_SCOPES
from tests.masjid_helpers import add_user, link, masjid_id, set_jumuah

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=TORONTO)  # Sunday
FRIDAY = date(2026, 10, 30)
WEEKDAYS = {day: {"dhuhr", "isha"} for day in range(5)}


@pytest.fixture
def user(db, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    set_jumuah(db, "user-a", ["Kanata Muslim Association"])
    return uid


def old_scopes(db, user) -> None:
    """Signed in before free/busy was asked for."""
    with Session(db) as session:
        session.scalars(select(GoogleToken).where(GoogleToken.user_id == user)).one().scopes = OLD_SCOPES
        session.commit()


def busy(db, http, user, first=FRIDAY, last=FRIDAY):
    with Session(db) as session:
        return busy_between(session, http, user, first, last, "America/Toronto")


# ---- The adapter ----


def test_busy_times_are_read_from_the_primary_calendar(db, http, user, fake_google):
    fake_google.busy["user-a"] = [("2026-10-30T17:00:00Z", "2026-10-30T18:00:00Z")]
    result = busy(db, http, user)
    assert result.checked
    assert result.busy == [(datetime(2026, 10, 30, 13, 0, tzinfo=TORONTO), datetime(2026, 10, 30, 14, 0, tzinfo=TORONTO))]
    [request] = fake_google.freebusy_requests()
    assert request.body["items"] == [{"id": "primary"}]
    # To the end of the next day, so Isha after midnight is covered.
    assert (request.body["timeMin"], request.body["timeMax"]) == ("2026-10-30T00:00:00-04:00", "2026-11-01T00:00:00-04:00")


def test_the_range_ends_at_a_local_midnight_on_a_clock_change(db, http, user, fake_google):
    # Nov 1, 2026 is 25 hours long in Toronto.
    busy(db, http, user, date(2026, 10, 31), date(2026, 10, 31))
    [request] = fake_google.freebusy_requests()
    assert (request.body["timeMin"], request.body["timeMax"]) == ("2026-10-31T00:00:00-04:00", "2026-11-02T00:00:00-05:00")


def test_one_call_covers_the_whole_14_day_window(db, http, user, fake_google):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    [request] = fake_google.freebusy_requests()
    assert (request.body["timeMin"], request.body["timeMax"]) == ("2026-10-25T00:00:00-04:00", "2026-11-09T00:00:00-05:00")


def test_the_prayers_calendar_is_never_counted(db, http, user, fake_google):
    # The first update makes the Prayers calendar, so the second answer has it (busy all day).
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    refresh(db, http, user, NOW + timedelta(minutes=5))
    assert len(fake_google.freebusy_requests()) == 2
    assert busy(db, http, user).busy == []
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "13:30"


@pytest.mark.parametrize("status", [403, 500])
def test_a_google_error_means_no_busy_times(db, http, user, fake_google, status):
    fake_google.freebusy_failure = status
    result = busy(db, http, user)
    assert (result.busy, result.status) == ([], "failed")


def test_no_free_busy_access_means_no_busy_times_and_no_request(db, http, user, fake_google):
    old_scopes(db, user)
    fake_google.busy["user-a"] = [("2026-10-30T16:00:00Z", "2026-10-30T20:00:00Z")]
    assert busy(db, http, user).status == "no_access"
    assert fake_google.freebusy_requests() == []


# ---- Busy times in the calendar update ----


def test_a_busy_first_jumuah_moves_to_the_earliest_that_fits(db, http, user, fake_google, ors_key):
    # Busy 1:00 to 1:40: the 1st Jumuah (1:30) clashes, the 2nd (2:30) fits.
    fake_google.busy["user-a"] = [("2026-10-30T17:00:00Z", "2026-10-30T17:40:00Z")]
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")
    assert clock(jumuah) == "14:30"
    # 1 hour after the 1st Jumuah, which is Jumuah's start time.
    assert jumuah["description"] == "Moved because of an event in your calendar (1 hour after Jumuah's start time)."
    # One free/busy call per update.
    assert len(fake_google.freebusy_requests()) == 1


def test_a_new_busy_time_sends_only_the_jumuah_and_its_drive_block(db, http, user, fake_google, ors_key):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "13:30"
    writes = len(fake_google.writes())

    fake_google.busy["user-a"] = [("2026-10-30T17:00:00Z", "2026-10-30T17:40:00Z")]
    refresh(db, http, user, NOW + timedelta(minutes=5))
    sent = fake_google.writes()[writes:]
    assert sorted(w.body["summary"] for w in sent) == ["Drive to KMA", "Jumuah at KMA"]
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "14:30"


def test_the_same_busy_times_mean_zero_writes(db, http, user, fake_google, ors_key):
    fake_google.busy["user-a"] = [("2026-10-30T17:00:00Z", "2026-10-30T17:40:00Z")]
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    writes = len(fake_google.writes())
    refresh(db, http, user, NOW + timedelta(minutes=5))
    assert len(fake_google.writes()) == writes


def test_a_free_busy_failure_never_fails_the_update(db, http, user, fake_google):
    fake_google.freebusy_failure = 500
    fetch(db, http, NOW)
    result = refresh(db, http, user, NOW)
    assert result.sent > 0
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "13:30"


def test_without_jumuah_masjids_free_busy_is_still_asked(db, http, user, fake_google):
    # Every prayer moves around busy times now, not just Jumuah.
    set_jumuah(db, "user-a", [])
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert len(fake_google.freebusy_requests()) == 1
    assert "Dhuhr at KMA" in [e["summary"] for e in on(google_events(fake_google), FRIDAY)]


def test_a_user_without_access_gets_the_earliest_jumuah(db, http, user, fake_google):
    old_scopes(db, user)
    fake_google.busy["user-a"] = [("2026-10-30T17:00:00Z", "2026-10-30T17:40:00Z")]
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert clock(titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")) == "13:30"
    assert fake_google.freebusy_requests() == []


def test_every_jumuah_clashing_gives_the_1st_jumuah_and_says_so(db, http, user, fake_google, ors_key):
    with Session(db) as session:
        row = session.scalars(select(UserSettings).where(UserSettings.user_id == user)).one()
        row.jumuah_pick_masjid_id, row.jumuah_pick_order = masjid_id(db, "Kanata Muslim Association"), 2
        session.commit()
    fake_google.busy["user-a"] = [("2026-10-30T16:00:00Z", "2026-10-30T20:00:00Z")]
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")
    assert clock(jumuah) == "13:30"
    assert jumuah["description"] == "Your event covers all of Jumuah's time today, so figure out a way to fit it in."
