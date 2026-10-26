"""Usage stats: only counts, saved once a day, and a private page only ADMIN_EMAIL can open."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import admin
from app.masjid_times.auto_link import auto_link
from app.masjid_times.mawaqit_list import ListRow, save_rows
from app.models import (
    BusyCheckJob,
    Masjid,
    MasjidSource,
    NightlyJob,
    UpdateJob,
    UsageStats,
    User,
    UserSettings,
)
from app.stats import counts, save_daily_stats
from tests.conftest import new_client, sign_in
from tests.masjid_helpers import add_masjid, link, user_id
from tests.setup_helpers import save_setup

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

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


def pick(db, masjids: list) -> None:
    """user-0, user-1, ... pick these masjids as their main masjid, in order."""
    with Session(db) as session:
        for n, masjid in enumerate(masjids):
            row = session.scalars(select(UserSettings).where(UserSettings.user_id == user_id(db, f"user-{n}"))).first()
            if row is None:
                row = UserSettings(user_id=user_id(db, f"user-{n}"), optional_saved=False, arrive_early_minutes=0)
                session.add(row)
            row.main_masjid_choice, row.main_masjid_id = "masjid", masjid
        session.commit()


def test_masjids_with_no_match_are_listed_with_their_user_counts_and_why(db, fake_google, fake_mawaqit, admin_email):
    make_users(db, fake_google, finished=0)
    kma, omar, linked = add_masjid(db, "Kanata Muslim Association"), add_masjid(db, "Jamia Omar", 45.31, -75.83), add_masjid(db, "Linked Masjid")
    link(db, linked, "linked")
    # 2 listed masjids within 100 m of Jamia Omar, so it wasn't linked.
    with Session(db) as session:
        save_rows(session, [ListRow("id/1", "Jami Omar", 45.3105, -75.83), ListRow("id/2", "Omar Centre", 45.3095, -75.83)], "file", NOW)
        session.commit()
    pick(db, [kma, kma, omar])
    # A home user and a masjid nobody picked don't count.
    add_masjid(db, "Nobody's Masjid")

    with browser_for(fake_google, 0) as browser:
        found = browser.get("/admin/stats").json()["no_match_masjids"]
    assert found == [
        {"id": str(kma), "name": "Kanata Muslim Association", "users": 2, "reason": "No listed masjid within 200 m"},
        {"id": str(omar), "name": "Jamia Omar", "users": 1, "reason": "2 listed masjids are close, so it wasn't linked"},
    ]


def test_a_masjid_unlinked_by_hand_says_so_and_an_address_is_never_shown(db, fake_google, admin_email):
    make_users(db, fake_google, finished=0)
    kma = add_masjid(db, "Kanata Muslim Association")
    link(db, kma, "kma-kanata")
    with Session(db) as session:
        typed = Masjid(source="user", address="12 Private Street, Ottawa", latitude=45.2, longitude=-75.9)
        session.add(typed)
        session.commit()
        typed_id = typed.id
        admin.unlink_mawaqit(session, str(kma), NOW)
    pick(db, [kma, typed_id])

    with browser_for(fake_google, 0) as browser:
        found = browser.get("/admin/stats").json()["no_match_masjids"]
    assert [(m["name"], m["reason"]) for m in found] == [
        ("Kanata Muslim Association", "Unlinked by hand"),
        ("(no name, picked by address)", "No listed masjid within 200 m"),
    ]
    assert "Private Street" not in json.dumps(found)


def test_automatic_links_are_listed_for_spot_checks(db, fake_google, admin_email):
    make_users(db, fake_google, finished=0)
    kma, mine = add_masjid(db, "Kanata Masjid", 45.3561, -75.9283), add_masjid(db, "My Masjid", 45.4, -75.6)
    nobody = add_masjid(db, "Picked In Setup Only", 45.32605, -75.71983)
    link(db, mine, "my-masjid")
    with Session(db) as session:
        save_rows(session, [
            ListRow("id/9793", "Kanata Muslim Association", 45.356128, -75.9283718),
            ListRow("id/14718", "MAC QIC", 45.326052, -75.7198339),
        ], "file", NOW)
        session.commit()
        for masjid in (kma, nobody):
            auto_link(session, session.get(Masjid, masjid), NOW)
        session.commit()
    pick(db, [kma, kma, mine])

    with browser_for(fake_google, 0) as browser:
        found = browser.get("/admin/stats").json()["auto_links"]
    assert sorted((m["name"], m["list_name"], m["mawaqit_url"], m["distance_m"], m["users"]) for m in found) == [
        ("Kanata Masjid", "Kanata Muslim Association", "https://mawaqit.net/en/id/9793", 6, 2),
        # Linked when someone picked it in setup, but nobody saved it yet.
        ("Picked In Setup Only", "MAC QIC", "https://mawaqit.net/en/id/14718", 0, 0),
    ]
