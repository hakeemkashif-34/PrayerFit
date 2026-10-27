"""Usage stats: total users, a graph of total users over time, and each masjid's users.

Counts only. No emails, names, or addresses ever leave app/stats.py.
"""

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app import admin
from app.models import Masjid, UserCountChange, UserSettings
from app.stats import (
    RANGES,
    MasjidCount,
    masjid_counts,
    stats_lines,
    total_users,
    user_totals,
)
from tests.conftest import new_client, sign_in
from tests.masjid_helpers import add_masjid, link, user_id

EMAILS = ["admin@example.com", "b@example.com", "c@example.com", "d@example.com"]


def make_users(db, fake_google, how_many: int = 3) -> list:
    """Users who signed in, user-0 to user-N."""
    for n, email in enumerate(EMAILS[:how_many]):
        with new_client() as browser:
            sign_in(browser, fake_google, sub=f"user-{n}", email=email)
    return [user_id(db, f"user-{n}") for n in range(how_many)]


def log(db, changes: dict) -> None:
    """Replace the sign-up and deletion counts: {hour in UTC: (signed up, deleted)}."""
    with Session(db) as session:
        session.query(UserCountChange).delete()
        for hour, (signed_up, deleted) in changes.items():
            session.add(UserCountChange(hour=hour, signed_up=signed_up, deleted=deleted))
        session.commit()


def logged(db) -> tuple[int, int]:
    """Everyone who signed up and everyone who deleted their account, over all hours."""
    with Session(db) as session:
        rows = session.execute(select(UserCountChange.signed_up, UserCountChange.deleted)).all()
    return sum(r[0] for r in rows), sum(r[1] for r in rows)


def totals(db, now: datetime, range_: str) -> tuple[str, list[tuple[str, int]]]:
    """The points as (Toronto time, total), easy to read in a test."""
    with Session(db) as session:
        step, points = user_totals(session, now, range_)
    return step, [(p.start.strftime("%Y-%m-%d %H:%M %Z"), p.total) for p in points]


def utc(*parts) -> datetime:
    return datetime(*parts, tzinfo=UTC)


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


# ---- The anonymous sign-up and deletion counts ----


def test_signing_up_counts_1_and_signing_in_again_counts_nothing(db, fake_google):
    make_users(db, fake_google)
    assert logged(db) == (3, 0)
    # The same person signing in again isn't a new user.
    with new_client() as browser:
        sign_in(browser, fake_google, sub="user-0", email=EMAILS[0])
    assert logged(db) == (3, 0)


def test_deleting_an_account_counts_1_deleted_and_keeps_the_sign_up(db, fake_google):
    make_users(db, fake_google)
    with browser_for(fake_google, 1) as browser:
        assert browser.delete("/account", headers={"Origin": "http://testserver"}).status_code == 200
    # The sign-up stays in the past, so the line goes up then down instead of vanishing.
    assert logged(db) == (3, 1)


def test_the_counts_hold_nothing_about_a_person(db):
    # Only the hour and 2 counts: no user ID, no email, nothing to join to users.
    columns = {column["name"] for column in inspect(db).get_columns("user_count_changes")}
    assert columns == {"hour", "signed_up", "deleted"}
    assert inspect(db).get_foreign_keys("user_count_changes") == []


# ---- Total users over time ----

# Noon on Oct 26, 2026 in Toronto (EDT, UTC-4).
NOON = datetime(2026, 10, 26, 12, 0, tzinfo=ZoneInfo("America/Toronto"))


def test_7_days_one_point_per_toronto_day_and_the_line_goes_down(db):
    log(db, {
        # Before the 7 days: already in the first point's total.
        utc(2026, 10, 1, 15): (2, 0),
        utc(2026, 10, 21, 15): (3, 0),
        # 10:30 pm on Oct 22 in Toronto is Oct 23 in UTC. It counts on Oct 22.
        utc(2026, 10, 23, 2): (1, 0),
        # Someone deleted their account.
        utc(2026, 10, 24, 18): (0, 1),
        utc(2026, 10, 25, 13): (1, 2),
    })
    step, points = totals(db, NOON, "7d")
    assert step == "day"
    assert points == [
        ("2026-10-20 00:00 EDT", 2),
        ("2026-10-21 00:00 EDT", 5),
        ("2026-10-22 00:00 EDT", 6),
        ("2026-10-23 00:00 EDT", 6),
        ("2026-10-24 00:00 EDT", 5),
        ("2026-10-25 00:00 EDT", 4),
        ("2026-10-26 00:00 EDT", 4),
    ]


def test_1_day_one_point_per_hour_in_toronto_time(db):
    log(db, {
        utc(2026, 10, 20, 12): (5, 0),
        # 9:15 am in Toronto.
        utc(2026, 10, 26, 13): (2, 0),
        utc(2026, 10, 26, 15): (0, 1),
    })
    step, points = totals(db, datetime(2026, 10, 26, 12, 40, tzinfo=NOON.tzinfo), "1d")
    assert step == "hour"
    # 24 hours, ending with the hour it is now.
    assert len(points) == 24
    assert points[0] == ("2026-10-25 13:00 EDT", 5)
    assert points[-6:] == [
        ("2026-10-26 07:00 EDT", 5),
        ("2026-10-26 08:00 EDT", 5),
        ("2026-10-26 09:00 EDT", 7),
        ("2026-10-26 10:00 EDT", 7),
        ("2026-10-26 11:00 EDT", 6),
        ("2026-10-26 12:00 EDT", 6),
    ]


def test_hours_over_the_fall_back_night_are_real_hours(db):
    # Nov 1, 2026: 1 am happens twice in Toronto, once in EDT, then again in EST.
    log(db, {utc(2026, 11, 1, 5): (1, 0), utc(2026, 11, 1, 6): (1, 0)})
    now = datetime(2026, 11, 1, 3, 30, tzinfo=ZoneInfo("America/Toronto"))
    _, points = totals(db, now, "1d")
    assert len(points) == 24
    assert points[-5:] == [
        ("2026-11-01 00:00 EDT", 0),
        ("2026-11-01 01:00 EDT", 1),
        ("2026-11-01 01:00 EST", 2),
        ("2026-11-01 02:00 EST", 2),
        ("2026-11-01 03:00 EST", 2),
    ]


def test_days_over_daylight_saving_are_calendar_days(db):
    log(db, {utc(2026, 10, 30, 15): (1, 0), utc(2026, 11, 2, 15): (1, 0)})
    now = datetime(2026, 11, 3, 12, tzinfo=ZoneInfo("America/Toronto"))
    _, points = totals(db, now, "5d")
    # Nov 1 is 25 hours long. Each point is still the next date at midnight.
    assert points == [
        ("2026-10-30 00:00 EDT", 1),
        ("2026-10-31 00:00 EDT", 1),
        ("2026-11-01 00:00 EDT", 1),
        ("2026-11-02 00:00 EST", 2),
        ("2026-11-03 00:00 EST", 2),
    ]


def test_all_time_starts_on_the_first_sign_up(db):
    log(db, {utc(2026, 10, 22, 15): (1, 0), utc(2026, 10, 25, 15): (1, 0)})
    step, points = totals(db, NOON, "all")
    assert step == "day"
    assert [p[0][:10] for p in points] == ["2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"]
    assert points[-1][1] == 2


@pytest.mark.parametrize(
    ("range_", "step", "how_many"),
    [("1d", "hour", 24), ("2d", "hour", 48), ("3d", "hour", 72), ("5d", "day", 5), ("7d", "day", 7), ("30d", "day", 30)],
)
def test_each_choice_has_the_right_number_of_points(db, range_, step, how_many):
    log(db, {utc(2026, 9, 1, 15): (1, 0)})
    found_step, points = totals(db, NOON, range_)
    assert (found_step, len(points)) == (step, how_many)
    assert {total for _, total in points} == {1}


def test_the_dropdown_choices():
    assert list(RANGES) == ["1d", "2d", "3d", "5d", "7d", "30d", "all"]


def test_nobody_ever_signed_up_means_no_points(db):
    for range_ in RANGES:
        assert totals(db, NOON, range_)[1] == []


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


def test_the_admin_sees_the_masjids_and_the_graph(db, fake_google, admin_email, set_today):
    a, b, c = make_users(db, fake_google)
    kma = add_masjid(db, "Kanata Muslim Association")
    pick(db, {a: kma, b: kma})
    log(db, {utc(2026, 10, 25, 16): (3, 0), utc(2026, 10, 26, 14): (0, 1)})
    set_today(date(2026, 10, 26))

    with browser_for(fake_google, 0) as browser:
        stats = browser.get("/admin/stats")
        week = browser.get("/admin/stats/users")
        day = browser.get("/admin/stats/users?range=1d")
    assert stats.status_code == 200
    assert stats.json() == {"masjids": [{"name": "Kanata Muslim Association", "users": 2, "mawaqit_linked": False}]}
    # 7 days unless the page asks for something else.
    assert week.json()["step"] == "day"
    assert week.json()["points"][-2:] == [
        {"start": "2026-10-25T00:00:00-04:00", "total": 3},
        {"start": "2026-10-26T00:00:00-04:00", "total": 2},
    ]
    assert day.json()["step"] == "hour"
    assert day.json()["points"][-1] == {"start": "2026-10-26T12:00:00-04:00", "total": 2}
    # No user details anywhere in the answers.
    for response in (stats, week, day):
        assert not any(email in json.dumps(response.json()) for email in EMAILS)


def test_an_unknown_range_is_refused(db, fake_google, admin_email):
    make_users(db, fake_google, 1)
    with browser_for(fake_google, 0) as browser:
        assert browser.get("/admin/stats/users?range=1y").status_code == 422


@pytest.mark.parametrize("who", ["someone else", "not signed in"])
def test_everyone_else_gets_page_not_found(db, fake_google, admin_email, who):
    make_users(db, fake_google)
    browser = browser_for(fake_google, 1) if who == "someone else" else new_client()
    with browser:
        responses = [browser.get("/admin/stats"), browser.get("/admin/stats/users")]
    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


def test_without_admin_email_nobody_can_see_it(db, fake_google, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    make_users(db, fake_google)
    with browser_for(fake_google, 0) as browser:
        assert browser.get("/admin/stats").status_code == 404


def test_the_daily_snapshot_table_is_gone(db):
    assert "usage_stats" not in inspect(db).get_table_names()
