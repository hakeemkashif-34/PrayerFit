"""Delete my account (DELETE /account, app/account.py).

Two users, both set up through the API with KMA as their main masjid, so
each has a Prayers calendar full of events, jobs, and drive times. user-a
deletes their account. Nothing of user-b's may change.
"""

import uuid
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import String, Text, Uuid, func, select, text
from sqlalchemy.orm import Session

from app.models import Base, Masjid, MasjidDayTimes, MasjidSource, User
from tests.conftest import new_client, sign_in
from tests.masjid_helpers import masjid_id, user_id
from tests.setup_helpers import setup_through_api

DAY = date(2026, 10, 25)


@pytest.fixture
def two_users(db, fake_google, fake_photon, set_today):
    """user-a and user-b, both finished setup. Returns user-a's browser."""
    set_today(DAY)
    browsers = {}
    for sub in ("user-b", "user-a"):
        browser = new_client()
        sign_in(browser, fake_google, sub=sub, email=f"{sub}@example.com")
        assert setup_through_api(browser, fake_photon).status_code == 200
        browsers[sub] = browser
    yield browsers["user-a"]
    for browser in browsers.values():
        browser.close()


def rows_about(db, who: uuid.UUID) -> dict[str, int]:
    """For every table, how many rows mention this user. Only tables with some.

    A row mentions them if any ID column is their ID, or any text column has
    their ID in it, like a job ID "busy:<user id>:2026-10-25T16:00".
    """
    found = {}
    with db.connect() as connection:
        for table in Base.metadata.sorted_tables:
            ids = [f"{c.name} = :who" for c in table.columns if isinstance(c.type, Uuid)]
            texts = [f"{c.name} LIKE :like" for c in table.columns if isinstance(c.type, (String, Text))]
            if not ids + texts:
                continue
            where = " OR ".join(ids + texts)
            count = connection.execute(
                text(f"SELECT count(*) FROM {table.name} WHERE {where}"), {"who": who, "like": f"%{who}%"}
            ).scalar_one()
            if count:
                found[table.name] = count
    return found


def delete(browser):
    return browser.delete("/account", headers={"Origin": "http://testserver"})


# ---- What gets deleted ----


def test_nothing_about_the_user_is_left_in_any_table(db, two_users, fake_google):
    a, b = user_id(db, "user-a"), user_id(db, "user-b")
    before_a, before_b = rows_about(db, a), rows_about(db, b)
    # They really had data everywhere first: sessions, tokens, settings, events, jobs, drive times.
    assert {"users", "sessions", "google_tokens", "user_settings", "prayer_calendars", "prayer_events"} <= set(before_a)

    response = delete(two_users)
    assert response.status_code == 200
    assert response.json() == {"google_cleaned": True}

    assert rows_about(db, a) == {}
    # user-b's rows are all still there, the same count in every table.
    assert rows_about(db, b) == before_b


def test_the_prayers_calendar_is_deleted_and_access_revoked(db, two_users, fake_google):
    assert len(fake_google.calendars_of("user-a")) == 1
    delete(two_users)
    # Every prayer event went with the calendar.
    assert fake_google.calendars_of("user-a") == []
    assert fake_google.accounts["user-a"].refresh_tokens == set()
    assert len(fake_google.revoked) == 1
    # user-b's calendar and access are untouched.
    assert len(fake_google.calendars_of("user-b")) == 1
    assert fake_google.accounts["user-b"].refresh_tokens


def test_nothing_else_in_their_google_account_is_touched(db, two_users, fake_google):
    [calendar] = fake_google.calendars_of("user-a")
    since = len(fake_google.requests)
    delete(two_users)
    # Exactly 1 Calendar API call: deleting the app's own Prayers calendar.
    assert [(r.method, r.path) for r in fake_google.requests[since:]] == [
        ("DELETE", f"/calendar/v3/calendars/{calendar.id}"),
    ]


def test_they_are_signed_out_everywhere(db, two_users, fake_google):
    # A 2nd browser, also signed in as user-a.
    with new_client() as phone:
        sign_in(phone, fake_google, sub="user-a", email="user-a@example.com")
        response = delete(two_users)
        assert "session=" in response.headers["set-cookie"] and "Max-Age=0" in response.headers["set-cookie"]
        assert two_users.get("/me").status_code == 401
        assert phone.get("/me").status_code == 401


def test_a_masjid_they_typed_in_goes_but_shared_masjids_stay(db, two_users):
    a = user_id(db, "user-a")
    with Session(db) as session:
        typed = Masjid(source="user", address="12 Private Street, Ottawa", latitude=45.2, longitude=-75.9, created_by_user_id=a)
        session.add(typed)
        session.flush()
        session.add(MasjidSource(masjid_id=typed.id, source="mawaqit", external_id="private-page"))
        adhan = {f"{p}_adhan": time(6 + n * 3) for n, p in enumerate(["fajr", "dhuhr", "asr", "maghrib", "isha"])}
        session.add(MasjidDayTimes(masjid_id=typed.id, local_date=DAY, source="mawaqit", jumuah=[],
                                      fetched_at=datetime(2026, 10, 25, tzinfo=UTC), **adhan))
        session.commit()
        typed_id = typed.id

    delete(two_users)
    with Session(db) as session:
        assert session.get(Masjid, typed_id) is None
        assert session.get(MasjidSource, typed_id) is None
        assert session.scalar(select(func.count()).select_from(MasjidDayTimes).where(MasjidDayTimes.masjid_id == typed_id)) == 0
    # KMA is public (OpenStreetMap), and user-b still uses it.
    assert masjid_id(db, "Kanata Muslim Association")


# ---- When Google can't help ----


def test_google_unreachable_still_deletes_everything_stored(db, two_users, fake_google):
    a = user_id(db, "user-a")
    fake_google.unreachable = True
    response = delete(two_users)
    assert response.status_code == 200
    assert response.json() == {"google_cleaned": False}
    assert rows_about(db, a) == {}
    with Session(db) as session:
        assert session.get(User, a) is None


def test_an_expired_google_sign_in_still_deletes_everything_stored(db, two_users, fake_google):
    a = user_id(db, "user-a")
    fake_google.kill_refresh_tokens("user-a")
    fake_google.expire_access_tokens()
    assert delete(two_users).json() == {"google_cleaned": False}
    assert rows_about(db, a) == {}
    # The calendar is still there for them to remove by hand. Nothing else was tried on it.
    assert len(fake_google.calendars_of("user-a")) == 1


def test_a_calendar_they_already_deleted_counts_as_done(db, two_users, fake_google):
    [calendar] = fake_google.calendars_of("user-a")
    fake_google.delete_calendar(calendar.id)
    assert delete(two_users).json() == {"google_cleaned": True}


# ---- Who can do it ----


def test_it_needs_sign_in(client):
    assert client.delete("/account", headers={"Origin": "http://testserver"}).status_code == 401


def test_another_site_cant_do_it(db, two_users):
    response = two_users.delete("/account", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert rows_about(db, user_id(db, "user-a"))
