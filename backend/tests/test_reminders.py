"""Prayer notifications: Google Calendar popup reminders from the 2 optional settings.

1. Before leaving: drive blocks.
2. Before home prayers: every prayer that isn't at the masjid.
Masjid prayer blocks, Jumuah too, never get one. Everyone starts with 5
minutes for both. None means no reminder at all, never the calendar's own defaults.

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
from tests.masjid_helpers import add_user, link, masjid_id, user_id

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


def test_the_defaults_5_minutes_before_leaving_and_at_home_and_none_at_the_masjid(db, http, user, fake_google):
    refresh(db, http, user, NOW)
    monday = on(google_events(fake_google), MONDAY)
    assert [(e["summary"], e["reminders"]) for e in monday] == [
        ("Fajr", popup(5)),
        ("Drive to KMA", popup(5)),
        ("Dhuhr at KMA", NONE),
        ("Asr", popup(5)),
        ("Maghrib", popup(5)),
        ("Drive to KMA", popup(5)),
        ("Isha at KMA", NONE),
    ]


def test_no_notification_on_both_means_no_reminders_at_all(db, http, user, fake_google):
    set_settings(db, user, leave_reminder_minutes=None, home_reminder_minutes=None)
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    # Drive blocks, masjid prayers, and home prayers: none of them, and never the calendar's defaults.
    assert {e["summary"] for e in on(events, MONDAY)} >= {"Drive to KMA", "Isha at KMA", "Fajr"}
    assert all(e["reminders"] == NONE for e in events)


def test_each_setting_sets_its_own_events(db, http, user, fake_google):
    set_settings(db, user, leave_reminder_minutes=15, home_reminder_minutes=20)
    refresh(db, http, user, NOW)
    monday = on(google_events(fake_google), MONDAY)
    # Masjid prayers never get a reminder, whatever the other 2 are.
    assert [(e["summary"], e["reminders"]) for e in monday] == [
        ("Fajr", popup(20)),
        ("Drive to KMA", popup(15)),
        ("Dhuhr at KMA", NONE),
        ("Asr", popup(20)),
        ("Maghrib", popup(20)),
        ("Drive to KMA", popup(15)),
        ("Isha at KMA", NONE),
    ]


def test_jumuah_gets_no_reminder_but_its_drive_does(db, http, user, fake_google):
    set_settings(db, user, leave_reminder_minutes=30)
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    assert titled(events, FRIDAY, "Jumuah at KMA")["reminders"] == NONE
    friday_drives = [e for e in on(events, FRIDAY) if e["summary"] == "Drive to KMA"]
    assert friday_drives and all(e["reminders"] == popup(30) for e in friday_drives)


def test_a_masjid_prayer_moved_home_uses_the_at_home_setting(db, http, user, fake_google):
    set_settings(db, user, home_reminder_minutes=10)
    # Busy from 7:30 to 8:45 pm on Monday, so the trip to Isha at KMA doesn't fit and Isha is at home.
    fake_google.busy["user-a"] = [("2026-10-26T23:30:00Z", "2026-10-27T00:45:00Z")]
    refresh(db, http, user, NOW)
    isha = titled(google_events(fake_google), MONDAY, "Isha")
    assert isha["reminders"] == popup(10)


def test_no_drive_block_means_no_before_leaving_reminder(db, http, fake_google, fake_mawaqit, monkeypatch):
    # No OpenRouteService key, so drive times are unknown and there are no drive blocks.
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={day: {"dhuhr", "isha"} for day in range(5)})
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    set_settings(db, uid, leave_reminder_minutes=15, home_reminder_minutes=None)
    refresh(db, http, uid, NOW)
    events = google_events(fake_google)
    assert not [e for e in events if e["summary"].startswith("Drive")]
    # Nothing has the 15-minute "before leaving" reminder.
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
    # Monday's Fajr was before 3 pm, so it keeps its old 5-minute reminder.
    assert titled(google_events(fake_google), MONDAY, "Fajr")["reminders"] == popup(5)
    assert titled(google_events(fake_google), MONDAY, "Asr")["reminders"] == popup(10)


# ---- The settings API ----


def optional(browser, **values):
    body = {"arrive_early_minutes": 5, "jumuah_arrive_early_minutes": 5, **values}
    return browser.put("/settings/optional", json=body, headers={"Origin": "http://testserver"})


def test_the_settings_start_at_the_defaults_and_save(db, fake_google):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        start = browser.get("/settings").json()
        assert (start["leave_reminder_minutes"], start["home_reminder_minutes"]) == (5, 5)
        # The removed "before iqamah" setting isn't there any more.
        assert "masjid_reminder_minutes" not in start
        # Any whole number from 0 to 60, not just the old dropdown's choices.
        response = optional(browser, leave_reminder_minutes=7, home_reminder_minutes=60)
        assert response.status_code == 200
        saved = browser.get("/settings").json()
    assert (saved["leave_reminder_minutes"], saved["home_reminder_minutes"]) == (7, 60)


@pytest.mark.parametrize("field", ["leave_reminder_minutes", "home_reminder_minutes", "arrive_early_minutes", "jumuah_arrive_early_minutes"])
@pytest.mark.parametrize("bad", [61, -1, 2.5, "5", None])
def test_only_whole_minutes_from_0_to_60_with_a_clear_message(db, fake_google, field, bad):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        response = optional(browser, **{field: bad})
    assert response.status_code == 422
    # One plain message the website shows, not a list of technical errors.
    assert response.json() == {"detail": {"message": "Enter a whole number of minutes from 0 to 60.", "field": field}}


def test_other_bad_answers_keep_the_usual_error(db, fake_google):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        response = optional(browser, prayer_color_id="99")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_skipping_the_optional_step_gives_the_defaults(db, fake_google):
    # Setup's Skip doesn't send the notification fields, so they get the defaults.
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        assert optional(browser).status_code == 200
        saved = browser.get("/settings").json()
    assert (saved["leave_reminder_minutes"], saved["home_reminder_minutes"]) == (5, 5)


def test_0_means_no_notification(db, http, user, fake_google):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        assert optional(browser, leave_reminder_minutes=0, home_reminder_minutes=0).status_code == 200
        saved = browser.get("/settings").json()
    assert (saved["leave_reminder_minutes"], saved["home_reminder_minutes"]) == (0, 0)
    refresh(db, http, user, NOW)
    assert all(e["reminders"] == NONE for e in google_events(fake_google))


def test_an_empty_setting_from_before_the_number_boxes_reads_as_0(db, fake_google):
    # Someone who picked "No notification" in the old dropdown has it empty. They keep it, shown as 0.
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-a", email="a@example.com")
        optional(browser)
        set_settings(db, user_id(db, "user-a"), leave_reminder_minutes=None, home_reminder_minutes=15)
        saved = browser.get("/settings").json()
    assert (saved["leave_reminder_minutes"], saved["home_reminder_minutes"]) == (0, 15)
