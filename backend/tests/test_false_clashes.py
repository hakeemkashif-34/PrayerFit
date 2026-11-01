"""Days where every prayer came out as a clash, and the 7 things that could cause it.

The report: one day, Fajr, Dhuhr, Asr, Maghrib, and Isha were all clashes,
and the only event that day was a call at 6:30 pm. A single short event
can't do that (test_a_6_30_call_alone_never_clashes), so something made the
whole day look busy.

Uses the same user as test_moving_calendar.py: KMA, Asr and Isha at the
masjid on Tuesdays, a 10 minute drive.
"""

from datetime import date, datetime

import pytest

from tests.calendar_helpers import google_events, on, rows
from tests.test_moving_calendar import NOW, TUESDAY, busy, run, titles, user  # noqa: F401

ALL_FIVE = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]


def clashes(db, user) -> list[tuple[date, str]]:
    return [(r.local_date, r.prayer) for r in rows(db, user) if r.fit == "clash"]


def test_a_6_30_call_alone_never_clashes(db, http, user, fake_google):
    busy(fake_google, ("18:30", "19:00"))
    run(db, http, user)
    assert clashes(db, user) == []


def test_reported_bug_an_all_day_event_with_a_call_makes_every_prayer_clash(db, http, user, fake_google):
    # An all-day event marked Busy in Google Calendar. Free/busy joins it with
    # the 6:30 pm call into one block, midnight to midnight.
    fake_google.busy["user-a"] = [("2026-10-27T00:00:00-04:00", "2026-10-28T00:00:00-04:00")]
    run(db, http, user)
    assert clashes(db, user) == []
    assert not any("clash" in t for t in titles(fake_google))


# ---- 1. The app's own Prayers calendar and drive blocks ----


def test_only_the_primary_calendar_is_asked_for(db, http, user, fake_google):
    busy(fake_google, ("18:30", "19:00"))
    run(db, http, user)
    assert {str(item["id"]) for r in fake_google.freebusy_requests() for item in r.body["items"]} == {"primary"}


def test_the_prayers_calendar_never_makes_a_prayer_clash_with_itself(db, http, user, fake_google):
    # The fake answers with the Prayers calendar busy for the whole window,
    # like a real answer with another calendar in it. Running twice means the
    # Prayers calendar already has every prayer and drive block in it.
    busy(fake_google, ("18:30", "19:00"))
    run(db, http, user)
    run(db, http, user)
    assert clashes(db, user) == []
    assert "Drive to KMA" in titles(fake_google)


# ---- 2. All-day and multi-day events ----


def test_a_multi_day_event_doesnt_count(db, http, user, fake_google):
    fake_google.busy["user-a"] = [("2026-10-26T10:00:00-04:00", "2026-10-28T18:00:00-04:00")]
    run(db, http, user)
    assert clashes(db, user) == []
    assert not any(r.fit == "moved" for r in rows(db, user))


def test_an_all_day_event_in_another_time_zone_doesnt_count(db, http, user, fake_google):
    # A Google Calendar set to UTC: its all-day event is 8 pm to 8 pm in Ottawa.
    fake_google.busy["user-a"] = [("2026-10-27T00:00:00Z", "2026-10-28T00:00:00Z")]
    run(db, http, user)
    assert clashes(db, user) == []


def test_an_all_day_event_on_the_23_hour_spring_day_doesnt_count():
    from zoneinfo import ZoneInfo

    from app.busy_times import without_all_day

    zone = ZoneInfo("America/Toronto")
    # March 8, 2026 is 23 hours long, since the clocks go forward.
    day = (datetime(2026, 3, 8, tzinfo=zone), datetime(2026, 3, 9, tzinfo=zone))
    almost = (datetime(2026, 3, 9, 1, tzinfo=zone), datetime(2026, 3, 9, 23, 59, tzinfo=zone))
    assert without_all_day([day, almost]) == [almost]


def test_a_long_day_of_classes_still_counts(db, http, user, fake_google):
    # 8 am to 9 pm is long, but it's real time the user is busy.
    busy(fake_google, ("08:00", "21:00"))
    run(db, http, user)
    assert (TUESDAY, "asr") in clashes(db, user)


# ---- 3. Free/busy failing or sending something odd ----

ODD_ANSWERS = {
    "no primary calendar": {"kind": "calendar#freeBusy", "calendars": {}},
    "errors for primary": {"calendars": {"primary": {"errors": [{"domain": "global", "reason": "backendError"}]}}},
    "unreadable busy times": {"calendars": {"primary": {"busy": [{"start": "soon"}]}}},
}


@pytest.mark.parametrize("answer", [500, *ODD_ANSWERS])
def test_a_google_error_on_the_first_update_flags_nothing(db, http, user, fake_google, caplog, answer):
    if answer == 500:
        fake_google.freebusy_failure = 500
    else:
        fake_google.freebusy_answer = ODD_ANSWERS[answer]
    run(db, http, user)
    assert clashes(db, user) == []
    assert not any(r.fit == "moved" for r in rows(db, user))
    assert not any("description" in e for e in google_events(fake_google))
    assert "Google free/busy failed" in caplog.text


@pytest.mark.parametrize("answer", [500, *ODD_ANSWERS])
def test_a_google_error_in_the_5_minute_check_flags_nothing_and_writes_nothing(db, http, user, fake_google, answer):
    from app.busy_checks import run_due_checks

    run(db, http, user)
    writes = len(fake_google.writes())
    if answer == 500:
        fake_google.freebusy_failure = 500
    else:
        fake_google.freebusy_answer = ODD_ANSWERS[answer]
    [result] = run_due_checks(db, http, NOW.replace(hour=9))
    assert result.status == "failed"
    assert len(fake_google.writes()) == writes
    assert clashes(db, user) == []


def test_an_answer_with_no_primary_calendar_never_undoes_a_move(db, http, user, fake_google):
    # Before the fix, a missing "primary" read as "free all day" and put moved prayers back.
    busy(fake_google, ("19:00", "20:30"))
    run(db, http, user)
    writes = len(fake_google.writes())
    fake_google.freebusy_answer = ODD_ANSWERS["no primary calendar"]
    from tests.calendar_helpers import refresh

    refresh(db, http, user, NOW.replace(hour=9))
    assert len(fake_google.writes()) == writes
    assert [r.prayer for r in rows(db, user) if r.fit == "moved"] == ["isha"]


# ---- 4. Events marked Free, and declined events ----


def test_free_and_declined_events_dont_count(db, http, user, fake_google):
    fake_google.primary_events["user-a"] = [
        {"start": "2026-10-27T15:00:00-04:00", "end": "2026-10-27T18:30:00-04:00", "transparency": "transparent"},
        {"start": "2026-10-27T19:00:00-04:00", "end": "2026-10-27T23:00:00-04:00", "responseStatus": "declined"},
    ]
    run(db, http, user)
    assert {r.fit for r in rows(db, user)} == {"normal"}


# ---- 5. Daylight saving: the clocks go back on Sunday, November 1, 2026 ----


def test_a_6_30_call_on_the_day_the_clocks_go_back_never_clashes(db, http, user, fake_google):
    busy(fake_google, ("18:30", "19:00"), day="2026-11-01", offset="-05:00")
    run(db, http, user)
    assert clashes(db, user) == []
    sunday = [r for r in rows(db, user) if r.local_date == date(2026, 11, 1) and r.kind == "prayer"]
    assert [r.prayer for r in sunday] == ["fajr", "dhuhr", "asr", "maghrib", "isha"]
    # Every prayer is on its own local date, in order, with no hour added or lost.
    starts = [r.starts_at for r in sunday]
    assert starts == sorted(starts)
    from zoneinfo import ZoneInfo

    assert {s.astimezone(ZoneInfo("America/Toronto")).date() for s in starts} == {date(2026, 11, 1)}


def test_each_window_is_right_on_the_day_the_clocks_go_back():
    from zoneinfo import ZoneInfo

    from app.fit_prayers import is_empty, prayer_windows
    from app.prayer_times import calculate_prayer_times

    zone = "America/Toronto"
    today = calculate_prayer_times(45.35, -75.91, date(2026, 11, 1), zone, "isna", "standard")
    tomorrow = calculate_prayer_times(45.35, -75.91, date(2026, 11, 2), zone, "isna", "standard")
    starts = {name: getattr(today, name).time for name in ["fajr", "dhuhr", "asr", "maghrib", "isha"]}
    windows = prayer_windows(starts, today.sunrise.time, tomorrow.fajr.time)
    assert not any(is_empty(w) for w in windows.values())
    # Fajr is after 1:59 am, so it's on standard time already.
    assert windows["fajr"].starts_at.utcoffset().total_seconds() == -5 * 3600
    # Isha ends halfway between Maghrib and the next Fajr, counted in real hours.
    maghrib, next_fajr = starts["maghrib"].astimezone(ZoneInfo("UTC")), tomorrow.fajr.time.astimezone(ZoneInfo("UTC"))
    halfway = maghrib + (next_fajr - maghrib) / 2
    assert abs((windows["isha"].ends_at - halfway).total_seconds()) < 60


def test_the_busy_times_asked_for_start_and_end_at_local_midnights_across_the_clock_change(db, http, user, fake_google):
    run(db, http, user)
    body = fake_google.freebusy_requests()[0].body
    # The window starts on Monday Oct 26 (daylight time) and ends after the change (standard time).
    assert body["timeMin"] == "2026-10-26T00:00:00-04:00"
    assert body["timeMax"].endswith("T00:00:00-05:00")


# ---- 6. Empty or backwards windows ----


def test_a_masjid_fajr_after_sunrise_uses_the_calculated_window(db, http, user, fake_google, fake_mawaqit):
    from tests.mawaqit_pages import conf, page, set_day

    # A typo on the masjid's page: Fajr at 7:40 am, after the 7:27 am sunrise.
    # Its window would be empty, so a busy Fajr would always be a clash.
    data = set_day(
        conf(), 10, 27,
        times=["07:40", "07:45", "12:48", "15:36", "18:01", "19:23"],
        iqamah=["+20", "13:00", "16:15", "+5", "19:40"],
    )
    fake_mawaqit.pages["kma-kanata"] = page(data)
    busy(fake_google, ("07:35", "07:55"))
    run(db, http, user)
    fajr = [r for r in rows(db, user) if r.local_date == TUESDAY and r.prayer == "fajr"][0]
    assert fajr.fit == "moved"


# ---- 7. Time zones: the server, the user, and Google ----


def test_the_servers_own_time_zone_changes_nothing(db, http, user, fake_google, monkeypatch):
    import time

    # Google answers in UTC, the server thinks it's in Tokyo, the user is in Ottawa.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        fake_google.busy["user-a"] = [("2026-10-27T22:30:00Z", "2026-10-27T23:00:00Z")]  # 6:30 pm in Ottawa
        run(db, http, user)
    finally:
        monkeypatch.undo()
        time.tzset()
    assert clashes(db, user) == []
    assert not any(r.fit == "moved" for r in rows(db, user))


# ---- The busy time in a clash description ----


def test_a_clash_says_when_the_user_was_busy(db, http, user, fake_google):
    busy(fake_google, ("15:00", "16:20"), ("16:20", "18:30"))
    run(db, http, user)
    [asr] = [e for e in on(google_events(fake_google), TUESDAY) if e["summary"] == "Asr (clash)"]
    assert asr["description"].endswith(" Busy from 3:00 to 6:30 pm.")


def test_busy_text_shows_both_halves_of_the_day_and_other_dates():
    from zoneinfo import ZoneInfo

    from app.event_plan import busy_text, clash_text

    zone = ZoneInfo("America/Toronto")

    def at(day, hour, minute=0):
        return datetime(2026, 10, day, hour, minute, tzinfo=zone)

    assert busy_text(at(27, 16, 30), at(27, 18, 15), TUESDAY, "America/Toronto") == "4:30 to 6:15 pm"
    assert busy_text(at(27, 11, 30), at(27, 13, 15), TUESDAY, "America/Toronto") == "11:30 am to 1:15 pm"
    assert busy_text(at(26, 23), at(27, 7), TUESDAY, "America/Toronto") == "Oct 26, 11:00 pm to 7:00 am"
    two = clash_text("Isha", [(at(27, 19), at(27, 20)), (at(27, 20, 5), at(27, 23, 59))], TUESDAY, "America/Toronto")
    assert two.endswith(" Busy from 7:00 to 8:00 pm and 8:05 to 11:59 pm.")
