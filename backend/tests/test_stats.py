"""Usage stats: total users, a graph of total users per day, and each masjid's users.

Counts only. No emails, names, or addresses ever leave app/stats.py.
"""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import inspect, update
from sqlalchemy.orm import Session

from app import admin
from app.models import Masjid, User, UserSettings
from app.stats import (
    Day,
    MasjidCount,
    daily_totals,
    masjid_counts,
    stats_lines,
    total_users,
)
from tests.conftest import new_client, sign_in
from tests.masjid_helpers import add_masjid, link, user_id

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
EMAILS = ["admin@example.com", "b@example.com", "c@example.com", "d@example.com"]


def make_users(db, fake_google, how_many: int = 3) -> list:
    """Users who signed in, user-0 to user-N."""
    for n, email in enumerate(EMAILS[:how_many]):
        with new_client() as browser:
            sign_in(browser, fake_google, sub=f"user-{n}", email=email)
    return [user_id(db, f"user-{n}") for n in range(how_many)]


def signed_up_at(db, user, when: datetime) -> None:
    with Session(db) as session:
        session.execute(update(User).where(User.id == user).values(created_at=when))
        session.commit()


def pick(db, picks: dict) -> None:
    """user -> the masjid they picked, or "home"."""
    with Session(db) as session:
        for user, masjid in picks.items():
            row = session.query(UserSettings).filter_by(user_id=user).first()
            if row is None:
                row = UserSettings(user_id=user, optional_saved=False, arrive_early_minutes=0)
                session.add(row)
            row.main_masjid_choice = "home" if masjid == "home" else "masjid"
            row.main_masjid_id = None if masjid == "home" else masjid
        session.commit()


# ---- Total users and the graph ----


def test_total_users_counts_everyone_who_signed_in(db, fake_google):
    make_users(db, fake_google)
    with Session(db) as session:
        assert total_users(session) == 3


def test_one_point_per_day_with_sign_ups_and_the_total_so_far(db, fake_google):
    a, b, c = make_users(db, fake_google)
    signed_up_at(db, a, datetime(2026, 10, 23, 15, 0, tzinfo=UTC))
    # 10:30 pm on Oct 23 in Ottawa, which is already Oct 24 in UTC. It counts on Oct 23.
    signed_up_at(db, b, datetime(2026, 10, 24, 2, 30, tzinfo=UTC))
    signed_up_at(db, c, datetime(2026, 10, 25, 16, 0, tzinfo=UTC))
    with Session(db) as session:
        points = daily_totals(session, NOW)
    # Every day up to today, even days nobody signed up.
    assert [(p.day.isoformat(), p.signed_up, p.total) for p in points] == [
        ("2026-10-23", 2, 2),
        ("2026-10-24", 0, 2),
        ("2026-10-25", 1, 3),
        ("2026-10-26", 0, 3),
    ]


def test_no_users_means_no_points(db):
    with Session(db) as session:
        assert daily_totals(session, NOW) == []


# ---- Masjids ----


def test_each_masjid_with_its_users_most_first(db, fake_google):
    a, b, c, d = make_users(db, fake_google, 4)
    kma, omar = add_masjid(db, "Kanata Muslim Association"), add_masjid(db, "Jamia Omar")
    link(db, kma, "kma-kanata")
    add_masjid(db, "Nobody's Masjid")
    with Session(db) as session:
        typed = Masjid(source="user", address="12 Private Street, Ottawa", latitude=45.2, longitude=-75.9)
        session.add(typed)
        session.commit()
        typed_id = typed.id
    pick(db, {a: kma, b: kma, c: omar, d: typed_id})

    with Session(db) as session:
        found = masjid_counts(session)
    # Masjids with 0 users and people who pray at home aren't there. An address is never shown.
    assert found == [
        MasjidCount("Kanata Muslim Association", 2, mawaqit_linked=True),
        MasjidCount("Jamia Omar", 1, mawaqit_linked=False),
        MasjidCount("(picked by address)", 1, mawaqit_linked=False),
    ]


def test_people_who_pray_at_home_dont_count_for_a_masjid(db, fake_google):
    a, b, _ = make_users(db, fake_google)
    kma = add_masjid(db, "Kanata Muslim Association")
    pick(db, {a: kma, b: "home"})
    with Session(db) as session:
        assert masjid_counts(session) == [MasjidCount("Kanata Muslim Association", 1, mawaqit_linked=False)]


# ---- The admin command ----


def test_the_command_prints_the_same_as_the_page():
    lines = stats_lines(3, [MasjidCount("Kanata Muslim Association", 2, True), MasjidCount("Jamia Omar", 1, False)])
    assert lines == [
        "Total users: 3",
        "",
        "Masjids:",
        "  Kanata Muslim Association: 2",
        "  Jamia Omar: 1  (no MAWAQIT times)",
    ]
    assert stats_lines(0, []) == ["Total users: 0", "", "Masjids:", "  None picked yet."]


def test_the_admin_command_prints_only_counts(db, fake_google, capsys):
    a, *_ = make_users(db, fake_google)
    pick(db, {a: add_masjid(db, "Kanata Muslim Association")})
    admin.main(["stats"])
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "Total users: 3", "", "Masjids:", "  Kanata Muslim Association: 1  (no MAWAQIT times)",
    ]
    assert "@" not in out


# ---- The private page ----


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "Admin@Example.com")


def browser_for(fake_google, n: int):
    browser = new_client()
    sign_in(browser, fake_google, sub=f"user-{n}", email=EMAILS[n])
    return browser


def test_the_admin_sees_the_stats(db, fake_google, admin_email, set_today):
    a, b, c = make_users(db, fake_google)
    for user in (a, b, c):
        signed_up_at(db, user, datetime(2026, 10, 25, 16, 0, tzinfo=UTC))
    kma = add_masjid(db, "Kanata Muslim Association")
    pick(db, {a: kma, b: kma})
    set_today(date(2026, 10, 26))

    with browser_for(fake_google, 0) as browser:
        response = browser.get("/admin/stats")
    assert response.status_code == 200
    assert response.json() == {
        "total_users": 3,
        "history": [
            {"day": "2026-10-25", "signed_up": 3, "total": 3},
            {"day": "2026-10-26", "signed_up": 0, "total": 3},
        ],
        "masjids": [{"name": "Kanata Muslim Association", "users": 2, "mawaqit_linked": False}],
    }
    # No user details anywhere in the answer.
    assert not any(email in json.dumps(response.json()) for email in EMAILS)


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


def test_the_daily_snapshot_table_is_gone(db):
    # The graph comes from users.created_at now, so nothing is saved each day.
    assert "usage_stats" not in inspect(db).get_table_names()
    assert Day.__dataclass_fields__.keys() == {"day", "signed_up", "total"}
