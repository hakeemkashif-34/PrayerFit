"""Queued calendar updates: one row per user, retried after Google errors, and run again if queued mid-run."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UpdateJob
from app.update_jobs import queue_update, run_due_updates
from tests.masjid_helpers import add_user

NOW = datetime(2026, 10, 25, 8, 0, tzinfo=ZoneInfo("America/Toronto"))


def queue(db, user, when=NOW, reason="mawaqit"):
    with Session(db) as session:
        queue_update(session, user, reason, when)
        session.commit()


def job(db, user) -> UpdateJob:
    with Session(db) as session:
        return session.get(UpdateJob, f"update:{user}")


def test_queuing_twice_makes_one_job(db, http, fake_google):
    user = add_user(fake_google, db, "user-a")
    queue(db, user)
    queue(db, user, NOW + timedelta(seconds=5))
    with Session(db) as session:
        assert len(session.scalars(select(UpdateJob)).all()) == 1
    assert [r.status for r in run_due_updates(db, http, NOW + timedelta(minutes=1))] == ["done"]


def test_a_google_error_is_retried_15_minutes_later(db, http, fake_google):
    user = add_user(fake_google, db, "user-a")
    fake_google.fail_event_write = {1: 500}
    queue(db, user)
    assert [r.status for r in run_due_updates(db, http, NOW)] == ["failed"]
    assert job(db, user).retry_at == NOW + timedelta(minutes=15)
    assert run_due_updates(db, http, NOW + timedelta(minutes=14)) == []
    assert [r.status for r in run_due_updates(db, http, NOW + timedelta(minutes=15))] == ["done"]
    # The events that failed went in on the retry, with no copies.
    ids = [e["id"] for e in fake_google.live_events(fake_google.calendars_of("user-a")[0].id)]
    assert len(ids) == len(set(ids)) == 70


def test_queued_again_while_running_runs_again(db, http, fake_google):
    user = add_user(fake_google, db, "user-a")
    queue(db, user)
    with Session(db) as session:
        row = session.get(UpdateJob, f"update:{user}")
        row.status, row.started_at = "running", NOW
        session.commit()
    queue(db, user, NOW + timedelta(seconds=30))
    assert job(db, user).status == "running"  # not taken from the running worker
    # The run finishes, sees the newer request, and goes back to pending.
    from app.update_jobs import _finish

    with Session(db) as session:
        _finish(session, user, "done", NOW + timedelta(minutes=1))
    assert job(db, user).status == "pending"


def test_a_user_who_hasnt_finished_setup_is_skipped(db, http, fake_google):
    user = add_user(fake_google, db, "user-a", finished=False)
    queue(db, user)
    assert [r.status for r in run_due_updates(db, http, NOW)] == ["skipped"]
