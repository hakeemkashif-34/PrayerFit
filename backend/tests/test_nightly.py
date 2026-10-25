"""Tests for the nightly job. Google is faked, and "now" is passed in."""

import dataclasses
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.models import NightlyJob, PrayerEvent, User, UserSettings
from app.nightly import due_date, job_id, run_due_jobs, run_now
from tests.conftest import fake_http_client, new_client, sign_in
from tests.setup_helpers import save_setup

TORONTO = ZoneInfo("America/Toronto")
VANCOUVER = ZoneInfo("America/Vancouver")


def at(day: date, hour: int, minute: int = 0, zone=TORONTO) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)


@pytest.fixture
def http(fake_google, fake_photon):
    with fake_http_client(fake_google, fake_photon) as client:
        yield client


def add_user(fake_google, db, sub: str, **setup) -> None:
    """A user who signed in and finished setup."""
    with new_client() as browser:
        sign_in(browser, fake_google, sub=sub, email=f"{sub}@example.com")
    save_setup(db, sub=sub, **setup)


def jobs(db) -> list[NightlyJob]:
    with DbSession(db) as session:
        return list(session.scalars(select(NightlyJob).order_by(NightlyJob.local_date)))


def live_events(fake_google, sub: str = "alice") -> list[dict]:
    calendars = fake_google.calendars_of(sub)
    return fake_google.live_events(calendars[0].id) if calendars else []


def event_dates(fake_google, sub: str = "alice") -> list[date]:
    return sorted({datetime.fromisoformat(e["start"]["dateTime"]).date() for e in live_events(fake_google, sub)})


# ---- When it's due ----


@pytest.mark.parametrize(
    "now, expected",
    [
        (at(date(2026, 10, 24), 2, 59), date(2026, 10, 23)),
        (at(date(2026, 10, 24), 3, 0), date(2026, 10, 24)),
        (at(date(2026, 10, 24), 23, 59), date(2026, 10, 24)),
        # Spring forward: 2:00 to 2:59 don't exist, but 3:00 does.
        (datetime(2026, 3, 8, 6, 59, tzinfo=ZoneInfo("UTC")), date(2026, 3, 7)),  # 1:59 EST
        (datetime(2026, 3, 8, 7, 0, tzinfo=ZoneInfo("UTC")), date(2026, 3, 8)),  # 3:00 EDT
        # Fall back: 1:30 happens twice, and both are still before 3:00.
        (datetime(2026, 11, 1, 5, 30, tzinfo=ZoneInfo("UTC")), date(2026, 10, 31)),  # 1:30 EDT
        (datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC")), date(2026, 10, 31)),  # 1:30 EST
        (datetime(2026, 11, 1, 8, 0, tzinfo=ZoneInfo("UTC")), date(2026, 11, 1)),  # 3:00 EST
    ],
)
def test_due_date_in_toronto(now, expected):
    assert due_date(now, "America/Toronto") == expected


def test_where_3_am_is_skipped_it_runs_at_4():
    # Helsinki jumps from 3:00 to 4:00 on March 29, 2026.
    just_before = datetime(2026, 3, 29, 0, 59, tzinfo=ZoneInfo("UTC"))  # 2:59 local
    jump = datetime(2026, 3, 29, 1, 0, tzinfo=ZoneInfo("UTC"))  # 4:00 local
    assert due_date(just_before, "Europe/Helsinki") == date(2026, 3, 28)
    assert due_date(jump, "Europe/Helsinki") == date(2026, 3, 29)


def test_runs_at_3_am_in_each_users_own_time_zone(fake_google, db, http):
    add_user(fake_google, db, "alice")  # Toronto
    add_user(fake_google, db, "bob", location=(49.2827, -123.1207), time_zone="America/Vancouver")
    day = date(2026, 10, 24)
    # Both of last night's jobs (October 23) are done.
    assert len(run_due_jobs(db, http, at(day - timedelta(days=1), 23, 0, VANCOUVER))) == 2

    # 3:30 am in Toronto is 12:30 am in Vancouver: only Alice's job is due.
    results = run_due_jobs(db, http, at(day, 3, 30))
    assert [r.job_id.endswith("2026-10-24") for r in results] == [True]
    assert [j.user_id for j in jobs(db) if j.local_date == day] == [results_user(db, "alice")]

    # 2:59 am in Vancouver: still nothing for Bob.
    assert run_due_jobs(db, http, at(day, 2, 59, VANCOUVER)) == []
    # 3:00 am in Vancouver.
    results = run_due_jobs(db, http, at(day, 3, 0, VANCOUVER))
    assert [r.status for r in results] == ["done"]
    assert {j.user_id for j in jobs(db) if j.local_date == day} == {
        results_user(db, "alice"), results_user(db, "bob")
    }


def results_user(db, sub: str):
    with DbSession(db) as session:
        return session.scalars(select(User.id).where(User.google_sub == sub)).one()


def test_no_job_for_a_night_before_setup(fake_google, db, http):
    add_user(fake_google, db, "alice")
    with DbSession(db) as session:
        session.execute(update(UserSettings).values(setup_completed_at=at(date(2026, 10, 24), 2, 0)))
        session.commit()

    # 2:30 am: last night's 3:00 am was before setup, so there's nothing to catch up.
    assert run_due_jobs(db, http, at(date(2026, 10, 24), 2, 30)) == []
    assert [r.status for r in run_due_jobs(db, http, at(date(2026, 10, 24), 3, 0))] == ["done"]


# ---- Never twice ----


def test_runs_once_per_user_per_day_even_if_started_twice(fake_google, db, http):
    add_user(fake_google, db, "alice")
    now = at(date(2026, 10, 24), 3, 0)

    first = run_due_jobs(db, http, now)
    writes = len(fake_google.writes())
    second = run_due_jobs(db, http, now + timedelta(minutes=1))

    assert [r.events_sent for r in first] == [70]
    assert second == []
    assert len(fake_google.writes()) == writes
    [job] = jobs(db)
    assert job.id == job_id(job.user_id, date(2026, 10, 24))
    assert (job.status, job.attempts) == ("done", 1)


def test_two_workers_at_the_same_moment_run_it_once(fake_google, fake_photon, db):
    add_user(fake_google, db, "alice")
    now = at(date(2026, 10, 24), 3, 0)
    results = []

    def worker():
        with fake_http_client(fake_google, fake_photon) as client:
            results.extend(run_due_jobs(db, client, now))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [r.status for r in results] == ["done"]
    assert len(live_events(fake_google)) == 70
    assert [w.method for w in fake_google.writes()].count("POST") == 71  # 1 calendar + 70 events
    assert jobs(db)[0].attempts == 1


def test_crashed_job_is_retried_without_duplicates(fake_google, db, http):
    add_user(fake_google, db, "alice")
    now = at(date(2026, 10, 24), 3, 0)
    run_due_jobs(db, http, now)
    # Pretend the worker died while running the job.
    with DbSession(db) as session:
        session.execute(update(NightlyJob).values(status="running", started_at=now))
        session.commit()

    assert run_due_jobs(db, http, now + timedelta(minutes=10)) == []  # might still be running
    results = run_due_jobs(db, http, now + timedelta(minutes=16))

    assert [(r.status, r.events_sent) for r in results] == [("done", 0)]
    assert len(live_events(fake_google)) == 70


# ---- Catching up ----


def test_a_missed_night_catches_up_when_the_worker_starts(fake_google, db, http):
    add_user(fake_google, db, "alice")
    run_due_jobs(db, http, at(date(2026, 10, 23), 3, 0))  # window Oct 23 to Nov 5

    # The server was off on the night of Oct 24 and starts again at 10 am on Oct 25.
    results = run_due_jobs(db, http, at(date(2026, 10, 25), 10, 0))

    assert [(r.status, r.events_sent) for r in results] == [("done", 10)]  # Nov 6 and Nov 7
    assert event_dates(fake_google)[-1] == date(2026, 11, 7)
    # Only the newest night ran. It covers everything the missed one would have done.
    assert [j.local_date for j in jobs(db)] == [date(2026, 10, 23), date(2026, 10, 25)]


def test_before_3_am_catch_up_runs_last_nights_job(fake_google, db, http):
    add_user(fake_google, db, "alice")

    results = run_due_jobs(db, http, at(date(2026, 10, 25), 1, 0))

    assert [r.status for r in results] == ["done"]
    assert jobs(db)[0].local_date == date(2026, 10, 24)


# ---- Sign-in and Google errors ----


def test_one_expired_sign_in_doesnt_stop_the_others(fake_google, db, http):
    add_user(fake_google, db, "alice")
    add_user(fake_google, db, "bob")
    add_user(fake_google, db, "carol")
    fake_google.expire_access_tokens()
    fake_google.kill_refresh_tokens("bob")

    results = run_due_jobs(db, http, at(date(2026, 10, 24), 3, 0))

    assert [r.status for r in results] == ["done", "needs_sign_in", "done"]
    assert len(live_events(fake_google, "alice")) == 70
    assert live_events(fake_google, "bob") == []
    assert len(live_events(fake_google, "carol")) == 70
    # Bob's events are saved and waiting for him.
    with DbSession(db) as session:
        assert len(session.scalars(select(PrayerEvent).where(PrayerEvent.sync_status == "pending")).all()) == 70


def test_signing_in_again_runs_the_skipped_job(fake_google, db, http):
    add_user(fake_google, db, "bob")
    fake_google.expire_access_tokens()
    fake_google.kill_refresh_tokens("bob")
    now = at(date(2026, 10, 24), 3, 0)
    run_due_jobs(db, http, now)

    with new_client() as browser:
        sign_in(browser, fake_google, sub="bob", email="bob@example.com")
    results = run_due_jobs(db, http, now + timedelta(hours=5))

    assert [(r.status, r.events_sent) for r in results] == [("done", 70)]
    assert len(live_events(fake_google, "bob")) == 70


def test_missing_calendar_access_isnt_retried_every_minute(fake_google, db, http):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="alice", email="alice@example.com",
                scopes="openid https://www.googleapis.com/auth/userinfo.email")
    save_setup(db, sub="alice")
    now = at(date(2026, 10, 24), 3, 0)

    assert [r.status for r in run_due_jobs(db, http, now)] == ["needs_sign_in"]
    assert run_due_jobs(db, http, now + timedelta(minutes=1)) == []
    assert jobs(db)[0].attempts == 1


def test_google_errors_are_retried_later(fake_google, db, http):
    add_user(fake_google, db, "alice")
    fake_google.fail_event_write = {5: 503}
    now = at(date(2026, 10, 24), 3, 0)

    first = run_due_jobs(db, http, now)
    assert [(r.status, r.events_sent) for r in first] == [("failed", 4)]
    assert run_due_jobs(db, http, now + timedelta(minutes=5)) == []  # waits 15 minutes

    retry = run_due_jobs(db, http, now + timedelta(minutes=15))

    assert [(r.status, r.events_sent) for r in retry] == [("done", 66)]
    assert len(live_events(fake_google)) == 70
    assert jobs(db)[0].attempts == 2


def test_gives_up_after_5_attempts(fake_google, db, http):
    add_user(fake_google, db, "alice")
    fake_google.fail_event_write = {n: 503 for n in range(1, 20)}
    now = at(date(2026, 10, 24), 3, 0)

    for minutes in range(0, 200, 15):
        run_due_jobs(db, http, now + timedelta(minutes=minutes))

    [job] = jobs(db)
    assert (job.status, job.attempts, job.retry_at) == ("failed", 5, None)


# ---- Rolling forward ----


def test_rolls_forward_each_night_and_never_deletes(fake_google, db, http):
    add_user(fake_google, db, "alice")

    for n in range(3):
        run_due_jobs(db, http, at(date(2026, 10, 24) + timedelta(days=n), 3, 0))

    dates = event_dates(fake_google)
    assert dates[0] == date(2026, 10, 24)  # past prayers stay
    assert dates[-1] == date(2026, 11, 8)
    assert len(live_events(fake_google)) == 16 * 5
    assert [r for r in fake_google.requests if r.method == "DELETE"] == []
    assert all(e.get("status") != "cancelled" for c in fake_google.calendars.values() for e in c.events.values())


def test_nightly_fixes_times_that_changed(fake_google, db, http, monkeypatch):
    add_user(fake_google, db, "alice")
    run_due_jobs(db, http, at(date(2026, 10, 24), 3, 0))

    # Say a fix to the maths moves every Isha 1 minute later.
    from app import calendar_window

    real = calendar_window.calculate_prayer_times

    def later_isha(*args, **kwargs):
        day = real(*args, **kwargs)
        isha = dataclasses.replace(day.isha, time=day.isha.time + timedelta(minutes=1))
        return dataclasses.replace(day, isha=isha)

    monkeypatch.setattr(calendar_window, "calculate_prayer_times", later_isha)
    results = run_due_jobs(db, http, at(date(2026, 10, 25), 3, 0))

    # 13 Ishas fixed (Oct 25 to Nov 6) plus the 5 prayers of the new day, Nov 7.
    assert results[0].events_sent == 13 + 5
    isha_writes = [w for w in fake_google.writes()[-18:] if w.body["summary"].startswith("Isha")]
    assert len(isha_writes) == 14


@pytest.mark.parametrize(
    "day, offset", [(date(2026, 11, 1), "-05:00"), (date(2026, 3, 8), "-04:00")]
)
def test_job_on_a_daylight_saving_day(fake_google, db, http, day, offset):
    add_user(fake_google, db, "alice", location=(43.6532, -79.3832))

    results = run_due_jobs(db, http, at(day, 3, 0))

    assert [r.status for r in results] == ["done"]
    assert jobs(db)[0].local_date == day
    events = live_events(fake_google)
    assert event_dates(fake_google) == [day + timedelta(days=n) for n in range(14)]
    assert all(e["start"]["dateTime"].endswith(offset) for e in events)


# ---- The run-now command ----


def test_run_now_then_again_doesnt_duplicate(fake_google, db, http):
    add_user(fake_google, db, "alice")
    now = at(date(2026, 10, 24), 14, 0)

    first = run_now(db, http, now)
    second = run_now(db, http, now + timedelta(minutes=1))
    forced = run_now(db, http, now + timedelta(minutes=2), force=True)

    assert [(r.status, r.events_sent) for r in first] == [("done", 70)]
    assert second[0].message == "Already ran today. Add --force to run it again."
    assert [(r.status, r.events_sent) for r in forced] == [("done", 0)]
    assert len(live_events(fake_google)) == 70
    # The worker sees the same job and doesn't run it again.
    assert run_due_jobs(db, http, now + timedelta(minutes=3)) == []


def test_run_now_for_one_email(fake_google, db, http):
    add_user(fake_google, db, "alice")
    add_user(fake_google, db, "bob")

    results = run_now(db, http, at(date(2026, 10, 24), 14, 0), email="bob@example.com")

    assert len(results) == 1
    assert live_events(fake_google, "alice") == []
    assert len(live_events(fake_google, "bob")) == 70


def test_users_without_setup_are_left_out(fake_google, db, http):
    with new_client() as browser:
        sign_in(browser, fake_google, sub="newbie", email="newbie@example.com")

    assert run_due_jobs(db, http, at(date(2026, 10, 24), 3, 0)) == []
    assert jobs(db) == []


def test_run_now_command_prints_what_it_did(fake_google, fake_photon, db, monkeypatch, capsys):
    from app import worker

    add_user(fake_google, db, "alice")
    monkeypatch.setattr(worker, "new_http_client", lambda: fake_http_client(fake_google, fake_photon))

    worker.main(["run-now", "--email", "alice@example.com"])
    worker.main(["run-now", "--email", "alice@example.com"])
    worker.main(["run-now", "--email", "nobody@example.com"])

    first, second, nobody = capsys.readouterr().out.strip().splitlines()
    assert first.endswith(": done, 70 events sent to Google")
    assert "Already ran today. Add --force to run it again." in second
    assert nobody == "No users with setup finished and email nobody@example.com."
