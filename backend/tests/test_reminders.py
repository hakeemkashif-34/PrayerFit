"""Prayer notifications: Google Calendar popup reminders from the 3 optional settings.

1. Before iqamah: masjid prayer blocks, Jumuah too.
2. Before leaving: drive blocks.
3. At home: every prayer that isn't at the masjid.
None means no reminder at all, never the calendar's own defaults.

KMA's made-up MAWAQIT page has Isha iqamah at 20:15, Dhuhr at 13:00, and
Jumuah at 13:30. The fake OpenRouteService says every drive is 14 minutes.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserSettings
from tests.calendar_helpers import fetch, google_events, on, refresh, titled
from tests.conftest import new_client, sign_in
from tests.masjid_helpers import add_user, link, masjid_id

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=TORONTO)  # Sunday
MONDAY = date(2026, 10, 26)
FRIDAY = date(2026, 10, 30)
NONE = {"useDefault": False, "overrides": []}


def popup(minutes: int) -> dict:
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]}


def set_settings(db, user, **values):
    with Session(db) as session:
        row = session.scalars(select(UserSettings).where(UserSettings.user_id == user)).one()
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


@pytest.fixture
def user(db, http, fake_google, fake_mawaqit, ors_key):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={day: {"dhuhr", "isha"} for day in range(5)})
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    return uid


def test_by_default_no_event_has_any_reminder(db, http, user, fake_google):
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    # Drive blocks, masjid prayers, and home prayers: none of them, and never the calendar's defaults.
    assert {e["summary"] for e in on(events, MONDAY)} >= {"Drive to KMA", "Isha at KMA", "Fajr"}
    assert all(e["reminders"] == NONE for e in events)


def test_each_setting_sets_its_own_events(db, http, user, fake_google):
    set_settings(db, user, masjid_reminder_minutes=10, leave_reminder_minutes=15, home_reminder_minutes=5)
    refresh(db, http, user, NOW)
    monday = on(google_events(fake_google), MONDAY)
    assert [(e["summary"], e["reminders"]) for e in monday] == [
        ("Fajr", popup(5)),
        ("Drive to KMA", popup(15)),
        ("Dhuhr at KMA", popup(10)),
        ("Asr", popup(5)),
        ("Maghrib", popup(5)),
        ("Drive to KMA", popup(15)),
        ("Isha at KMA", popup(10)),
    ]


def test_jumuah_uses_the_before_iqamah_setting(db, http, user, fake_google):
    set_settings(db, user, masjid_reminder_minutes=20, leave_reminder_minutes=30)
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    assert titled(events, FRIDAY, "Jumuah at KMA")["reminders"] == popup(20)
    friday_drives = [e for e in on(events, FRIDAY) if e["summary"] == "Drive to KMA"]
    assert friday_drives and all(e["reminders"] == popup(30) for e in friday_drives)


def test_a_masjid_prayer_moved_home_uses_the_at_home_setting(db, http, user, fake_google):
    set_settings(db, user, masjid_reminder_minutes=10, home_reminder_minutes=5)
    # Busy from 7:30 to 8:45 pm on Monday, so the trip to Isha at KMA doesn't fit and Isha is at home.
    fake_google.busy["user-a"] = [("2026-10-26T23:30:00Z", "2026-10-27T00:45:00Z")]
    refresh(db, http, user, NOW)
    isha = titled(google_events(fake_google), MONDAY, "Isha")
    assert isha["reminders"] == popup(5)


def test_no_drive_block_means_no_before_leaving_reminder(db, http, fake_google, fake_mawaqit, monkeypatch):
    # No OpenRouteService key, so drive times are unknown and there are no drive blocks.
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={day: {"dhuhr", "isha"} for day in range(5)})
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    set_settings(db, uid, leave_reminder_minutes=15)
    refresh(db, http, uid, NOW)
    events = google_events(fake_google)
    assert not [e for e in events if e["summary"].startswith("Drive")]
    assert all(e["reminders"] == NONE for e in events)


def test_changing_a_setting_only_sends_the_events_it_changes(db, http, user, fake_google):
    refresh(db, http, user, NOW)
    before = len(fake_google.writes())
    # 3 pm on Monday: Fajr and Dhuhr are already past, so they're never touched.
    later = datetime(2026, 10, 26, 15, 0, tzinfo=TORONTO)
    set_settings(db, user, home_reminder_minutes=10)
    refresh(db, http, user, later)
    sent = fake_google.writes()[before:]
    summaries = {r.body["summary"] for r in sent}
    # Only home prayers changed (weekends are all at home). Drive blocks and masjid prayers stay as they were.
    assert summaries == {"Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"}
    assert all(r.body["reminders"] == popup(10) for r in sent)
    assert all(datetime.fromisoformat(r.body["start"]["dateTime"]) > later for r in sent)
    # Monday's Fajr was before 3 pm, so it keeps no reminder.
    assert titled(google_events(fake_google), MONDAY, "Fajr")["reminders"] == NONE
    assert titled(google_events(fake_google), MONDAY, "Asr")["reminders"] == popup(10)


# ---- The settings API ----


def optional(browser, **values):
    body = {"arrive_early_minutes": 5, "jumuah_arrive_early_minutes": 5, **values}
    return browser.put("/settings/optional", json=body, headers={"Origin": "http://testserver"})


def test_the_settings_start_empty_and_save(db, fake_google):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        start = browser.get("/settings").json()
        assert (start["masjid_reminder_minutes"], start["leave_reminder_minutes"], start["home_reminder_minutes"]) == (
            None, None, None,
        )
        response = optional(browser, masjid_reminder_minutes=5, leave_reminder_minutes=30, home_reminder_minutes=None)
        assert response.status_code == 200
        saved = browser.get("/settings").json()
    assert (saved["masjid_reminder_minutes"], saved["leave_reminder_minutes"], saved["home_reminder_minutes"]) == (
        5, 30, None,
    )


@pytest.mark.parametrize("bad", [7, 0, 60, "5", -5])
def test_only_the_dropdown_choices_are_allowed(db, fake_google, bad):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        assert optional(browser, home_reminder_minutes=bad).status_code == 422
