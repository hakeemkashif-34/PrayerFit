"""Usage stats: only counts, saved once a day, and a private page only ADMIN_EMAIL can open."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import admin
from app.models import BusyCheckJob, MasjidSource, NightlyJob, UpdateJob, UsageStats, User
from app.stats import counts, save_daily_stats
from tests.conftest import new_client, sign_in
from tests.masjid_helpers import add_masjid, link, user_id
from tests.setup_helpers import save_setup

TORONTO = ZoneInfo("America/Toronto")
EMAILS = ["admin@example.com", "b@example.com", "c@example.com"]


def make_users(db, fake_google, finished: int = 2) -> list:
    """3 users who signed in. The first `finished` of them finished setup."""
    for n, email in enumerate(EMAILS):
        with new_client() as browser:
            sign_in(browser, fake_google, sub=f"user-{n}", email=email)
        if n < finished:
            save_setup(db, sub=f"user-{n}")
    return [user_id(db, f"user-{n}") for n in range(len(EMAILS))]


def add_job(db, table, user, status: str, finished_at: datetime) -> None:
    with Session(db) as session:
        values = {"id": f"{table.__tablename__[:4]}:{user}:{finished_at:%Y%m%d%H%M}", "user_id": user, "status": status,
                  "finished_at": finished_at, "events_sent": 0}
        if table is NightlyJob:
            values.update(local_date=finished_at.date(), attempts=1)
        elif table is UpdateJob:
            values.update(reason="test", requested_at=finished_at, attempts=1)
            values["id"] = f"update:{user}"
        else:
            values.update(block_start=finished_at)
        session.add(table(**values))
        session.commit()


# ---- The counts ----


def test_the_4_counts(db, fake_google):
    users = make_users(db, fake_google)
    now = datetime.now(UTC)
    # One user signed up 10 days ago, so they aren't new this week.
    with Session(db) as session:
        session.execute(update(User).where(User.id == users[2]).values(created_at=now - timedelta(days=10)))
        session.commit()
    # Active: a nightly job yesterday, and a 15-minute check today. A failed update doesn't count,
    # and neither does a check 3 days ago.
    add_job(db, NightlyJob, users[0], "done", now - timedelta(days=1))
    add_job(db, BusyCheckJob, users[0], "done", now - timedelta(minutes=5))
    add_job(db, UpdateJob, users[1], "failed", now - timedelta(hours=1))
    add_job(db, BusyCheckJob, users[2], "done", now - timedelta(days=3))

    with Session(db) as session:
        found = counts(session, now)
    assert (found.signed_up, found.finished_setup, found.active, found.new_this_week) == (3, 2, 1, 2)


def test_a_settings_update_counts_as_active(db, fake_google):
    users = make_users(db, fake_google)
    now = datetime.now(UTC)
    add_job(db, UpdateJob, users[1], "done", now - timedelta(hours=47))
    with Session(db) as session:
        assert counts(session, now).active == 1


def test_the_admin_command_prints_only_counts(db, fake_google, capsys):
    make_users(db, fake_google)
    admin.main(["stats"])
    printed = capsys.readouterr().out
    assert printed.splitlines() == [
        "Signed up: 3",
        "Finished setup: 2",
        "Active (calendar updated in the last 2 days): 0",
        "New this week: 3",
    ]
    assert "@" not in printed and "user-" not in printed


# ---- Saved once a day ----


def test_the_counts_are_saved_once_a_day_after_4_am(db, fake_google, http):
    make_users(db, fake_google)
    before_4 = datetime(2026, 10, 26, 3, 59, tzinfo=TORONTO)
    assert save_daily_stats(db, http, before_4) is False

    at_4 = datetime(2026, 10, 26, 4, 0, tzinfo=TORONTO)
    assert save_daily_stats(db, http, at_4) is True
    # The worker runs every minute, but the date is the row's ID.
    assert save_daily_stats(db, http, at_4 + timedelta(minutes=1)) is False
    assert save_daily_stats(db, http, at_4 + timedelta(days=1)) is True

    with Session(db) as session:
        rows = list(session.scalars(select(UsageStats).order_by(UsageStats.day)))
    assert [r.day for r in rows] == [date(2026, 10, 26), date(2026, 10, 27)]
    assert (rows[0].signed_up, rows[0].finished_setup) == (3, 2)


def test_saved_stats_have_only_numbers(db):
    columns = {c.name for c in UsageStats.__table__.columns}
    assert columns == {"day", "signed_up", "finished_setup", "active", "new_this_week", "saved_at"}


# ---- The private page ----


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "Admin@Example.com")


def browser_for(fake_google, n: int):
    browser = new_client()
    sign_in(browser, fake_google, sub=f"user-{n}", email=EMAILS[n])
    return browser


def test_the_admin_sees_the_stats(db, fake_google, http, admin_email):
    make_users(db, fake_google)
    save_daily_stats(db, http, datetime(2026, 10, 26, 5, 0, tzinfo=TORONTO))
    with browser_for(fake_google, 0) as browser:
        response = browser.get("/admin/stats")
    assert response.status_code == 200
    body = response.json()
    assert (body["signed_up"], body["finished_setup"], body["active"], body["new_this_week"]) == (3, 2, 0, 3)
    assert body["history"] == [{"day": "2026-10-26", "signed_up": 3, "active": 0}]
    # No user details anywhere in the answer.
    text = json.dumps(body)
    assert not any(email in text for email in EMAILS)


@pytest.mark.parametrize("who", ["someone else", "not signed in"])
def test_everyone_else_gets_page_not_found(db, fake_google, admin_email, who):
    make_users(db, fake_google)
    browser = browser_for(fake_google, 1) if who == "someone else" else new_client()
    with browser:
        response = browser.get("/admin/stats")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_without_admin_email_nobody_can_see_it(db, fake_google, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    make_users(db, fake_google)
    with browser_for(fake_google, 0) as browser:
        assert browser.get("/admin/stats").status_code == 404


def test_masjid_times_lists_failing_and_old_reads(db, fake_google, fake_mawaqit, admin_email):
    make_users(db, fake_google)
    now = datetime.now(UTC)
    fresh, failing, old = add_masjid(db, "Fresh Masjid"), add_masjid(db, "Failing Masjid"), add_masjid(db, "Old Masjid")
    for masjid, slug in ((fresh, "fresh"), (failing, "failing"), (old, "old")):
        link(db, masjid, slug)
    with Session(db) as session:
        session.get(MasjidSource, fresh).last_success_at = now - timedelta(hours=1)
        row = session.get(MasjidSource, failing)
        row.last_success_at, row.consecutive_failures, row.last_error = now - timedelta(hours=2), 1, "status 403"
        session.get(MasjidSource, old).last_success_at = now - timedelta(days=2)
        session.commit()

    with browser_for(fake_google, 0) as browser:
        problems = browser.get("/admin/stats").json()["masjid_times"]
    assert [(p["name"], p["error"]) for p in problems] == [("Failing Masjid", "status 403"), ("Old Masjid", None)]
    assert all(p["source"] == "mawaqit" and p["last_success_at"] for p in problems)
