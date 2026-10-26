"""The 5-minute busy check: today and tomorrow, stable IDs, and never undoing a move.

Uses the same user as test_moving_calendar.py: Asr and Isha at KMA on
Tuesdays, Isha iqamah 7:40 pm, a 10 minute drive, 5 minutes early.
"""

import threading
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.busy_checks import block_start, check_id, run_due_checks
from app.models import BusyCheckJob, GoogleToken, WeeklyMasjidPrayers
from tests.calendar_helpers import clock, fetch, google_events, refresh, titled
from tests.conftest import fake_http_client
from tests.fake_google import OLD_SCOPES
from tests.test_moving_calendar import NOW, TORONTO, TUESDAY, busy, moved, run, titles, user  # noqa: F401

ALL_AT_KMA = ["Fajr", "Dhuhr", "Drive to KMA", "Asr at KMA", "Maghrib", "Drive to KMA", "Isha at KMA"]


def check(db, http, now):
    return run_due_checks(db, http, now)


def calendar_requests(fake_google, since: int) -> list[str]:
    """Every Calendar API request after the first `since`, as "METHOD path"."""
    return [f"{r.method} {r.path}" for r in fake_google.requests[since:]]


def jobs(db) -> list[BusyCheckJob]:
    with Session(db) as session:
        return list(session.scalars(select(BusyCheckJob)))


# ---- The rule ----


def test_a_new_event_moves_the_prayer_and_removing_it_puts_it_back(db, http, user, fake_google):
    run(db, http, user)
    assert titles(fake_google) == ALL_AT_KMA

    busy(fake_google, ("19:00", "20:30"))
    writes = len(fake_google.writes())
    [result] = check(db, http, NOW.replace(hour=9))
    assert (result.status, result.events_sent) == ("done", 2)  # Isha, and deleting its drive block
    assert len(fake_google.writes()) == writes + 2
    isha = titled(google_events(fake_google), TUESDAY, "Isha")
    assert clock(isha) == "20:30"
    assert isha["description"] == moved("1 hour 7 minutes after Isha's start time")

    # The event is removed. The next check, 5 minutes later, puts Isha back at KMA.
    fake_google.busy["user-a"] = []
    [result] = check(db, http, NOW.replace(hour=9, minute=5))
    assert (result.status, result.events_sent) == ("done", 2)
    assert titles(fake_google) == ALL_AT_KMA
    assert clock(titled(google_events(fake_google), TUESDAY, "Isha at KMA")) == "19:40"


def test_only_today_and_tomorrow_are_checked(db, http, user, fake_google):
    run(db, http, user)
    requests = len(fake_google.freebusy_requests())
    # Busy over Thursday's Isha, 3 days away. Only the nightly job looks that far.
    busy(fake_google, ("19:00", "20:30"), day="2026-10-29")
    writes = len(fake_google.writes())
    check(db, http, NOW.replace(hour=9))
    request = fake_google.freebusy_requests()[requests]
    assert (request.body["timeMin"], request.body["timeMax"]) == ("2026-10-26T00:00:00-04:00", "2026-10-29T00:00:00-04:00")
    assert len(fake_google.writes()) == writes

    refresh(db, http, user, NOW.replace(hour=9, minute=5))
    assert len(fake_google.writes()) > writes


def test_nothing_changed_means_zero_writes_and_only_a_free_busy_call(db, http, user, fake_google):
    run(db, http, user)
    since = len(fake_google.requests)
    for minute in (0, 5, 10):
        [result] = check(db, http, NOW.replace(hour=9, minute=minute))
        assert (result.status, result.events_sent) == ("done", 0)
    # No event writes, and not even the calendar lookup. Just 3 free/busy calls.
    assert calendar_requests(fake_google, since) == ["POST /calendar/v3/freeBusy"] * 3


def test_the_prayers_calendar_never_counts_as_busy(db, http, user, fake_google):
    # The fake answers that the Prayers calendar is busy all day. Only primary counts.
    run(db, http, user)
    writes = len(fake_google.writes())
    check(db, http, NOW.replace(hour=9))
    assert len(fake_google.writes()) == writes
    assert titles(fake_google) == ALL_AT_KMA


# ---- When free/busy fails ----


def test_a_free_busy_failure_leaves_every_event_as_it_is(db, http, user, fake_google):
    busy(fake_google, ("19:00", "20:30"), ("15:00", "18:30"))
    run(db, http, user)
    since, writes = len(fake_google.requests), len(fake_google.writes())

    fake_google.freebusy_failure = 500
    [result] = check(db, http, NOW.replace(hour=9))
    assert result.status == "failed"
    assert len(fake_google.writes()) == writes
    assert calendar_requests(fake_google, since) == ["POST /calendar/v3/freeBusy"]
    assert clock(titled(google_events(fake_google), TUESDAY, "Isha")) == "20:30"
    assert clock(titled(google_events(fake_google), TUESDAY, "Asr (clash)")) == "16:15"

    # The next block tries again, and works once Google answers.
    fake_google.freebusy_failure = None
    fake_google.busy["user-a"] = []
    [result] = check(db, http, NOW.replace(hour=9, minute=5))
    assert result.status == "done"
    assert titles(fake_google) == ALL_AT_KMA


# ---- Events that already started ----


def test_events_that_already_started_are_never_moved(db, http, user, fake_google):
    run(db, http, user)
    # Tuesday 7:30 pm: the drive to Isha left at 7:25, and Maghrib (6:01) is over.
    now = datetime(2026, 10, 27, 19, 30, tzinfo=TORONTO)
    fetch(db, http, now)  # so KMA's times are still fresh
    busy(fake_google, ("17:30", "18:30"), ("19:31", "20:30"))
    writes = len(fake_google.writes())
    [result] = check(db, http, now)
    assert (result.status, result.events_sent) == ("done", 0)
    assert len(fake_google.writes()) == writes
    events = google_events(fake_google)
    assert clock(titled(events, TUESDAY, "Isha at KMA")) == "19:40"
    assert clock(titled(events, TUESDAY, "Maghrib")) == "18:01"


def test_a_moved_prayer_is_never_put_in_the_past(db, http, user, fake_google):
    # Isha at home on Tuesdays, so its normal time is the adhan, 7:23 pm.
    with Session(db) as session:
        session.query(WeeklyMasjidPrayers).filter_by(user_id=user, weekday=1).one().isha = False
        session.commit()
    busy(fake_google, ("19:00", "20:30"))
    run(db, http, user)
    assert clock(titled(google_events(fake_google), TUESDAY, "Isha")) == "20:30"

    # At 7:46 pm the meeting turns out to end at 7:45. The earliest free time is now, not 7:45.
    busy(fake_google, ("19:00", "19:45"))
    check(db, http, datetime(2026, 10, 27, 19, 46, tzinfo=TORONTO))
    assert clock(titled(google_events(fake_google), TUESDAY, "Isha")) == "19:46"


# ---- Who gets checked, and the job IDs ----


def test_users_without_free_busy_access_are_not_checked(db, http, user, fake_google):
    run(db, http, user)
    with Session(db) as session:
        session.scalars(select(GoogleToken).where(GoogleToken.user_id == user)).one().scopes = OLD_SCOPES
        session.commit()
    requests = len(fake_google.freebusy_requests())
    assert check(db, http, NOW.replace(hour=9)) == []
    assert len(fake_google.freebusy_requests()) == requests


def test_users_who_need_to_sign_in_again_are_not_checked(db, http, user, fake_google):
    run(db, http, user)
    with Session(db) as session:
        session.scalars(select(GoogleToken).where(GoogleToken.user_id == user)).one().needs_reauth = True
        session.commit()
    assert check(db, http, NOW.replace(hour=9)) == []


def test_one_check_per_user_per_5_minutes(db, http, user, fake_google):
    run(db, http, user)
    requests = len(fake_google.freebusy_requests())
    assert len(check(db, http, NOW.replace(hour=9, minute=1))) == 1
    # Same block: the worker checks every minute, but the job already ran.
    assert check(db, http, NOW.replace(hour=9, minute=4, second=59)) == []
    assert len(check(db, http, NOW.replace(hour=9, minute=5))) == 1
    assert len(fake_google.freebusy_requests()) == requests + 2
    assert sorted(j.id for j in jobs(db)) == sorted(
        [check_id(user, NOW.replace(hour=9)), check_id(user, NOW.replace(hour=9, minute=5))]
    )
    assert check_id(user, NOW.replace(hour=9, minute=7)) == f"busy:{user}:2026-10-26T13:05"


def test_two_workers_in_the_same_block_check_once(db, user, fake_google, fake_photon, fake_mawaqit, fake_ors, http):
    run(db, http, user)
    requests = len(fake_google.freebusy_requests())
    results = []

    def worker():
        with fake_http_client(fake_google, fake_photon, fake_mawaqit, fake_ors) as client:
            results.extend(check(db, client, NOW.replace(hour=9)))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [r.status for r in results] == ["done"]
    assert len(fake_google.freebusy_requests()) == requests + 1


def test_old_checks_are_deleted(db, http, user, fake_google):
    run(db, http, user)
    old = NOW - timedelta(days=3)
    with Session(db) as session:
        session.add(BusyCheckJob(id=check_id(user, old), user_id=user, block_start=block_start(old), status="done", events_sent=0))
        session.commit()
    check(db, http, NOW.replace(hour=9))
    assert [j.id for j in jobs(db)] == [check_id(user, NOW.replace(hour=9))]
