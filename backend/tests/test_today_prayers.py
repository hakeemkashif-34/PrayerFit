"""Tests for POST /prayers/today. Google is faked, so nothing real is written."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.models import GoogleToken, PrayerEvent
from app.prayer_times import calculate_prayer_times
from tests.conftest import sign_in
from tests.setup_helpers import save_setup

OTTAWA = {"latitude": 45.4215, "longitude": -75.6972, "timezone": "America/Toronto"}
DAY = date(2026, 10, 24)

# Further east than Ottawa, so every prayer time moves.
MONTREAL = (45.5017, -73.5673)


@pytest.fixture
def signed_in(client, fake_google, set_today, db):
    """Signed in, setup finished (Ottawa, ISNA, standard Asr, at home), and it's noon on DAY."""
    sign_in(client, fake_google)
    save_setup(db)
    set_today(DAY)
    return client


def _only_calendar(fake):
    calendars = fake.calendars_of("user-a")
    assert len(calendars) == 1
    return calendars[0]


def test_adds_the_five_prayers(signed_in, fake_google):
    response = signed_in.post("/prayers/today")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == "2026-10-24"
    assert body["calendar"] == "Prayers"
    assert [e["prayer"] for e in body["events"]] == ["fajr", "dhuhr", "asr", "maghrib", "isha"]
    assert all(e["sync_status"] == "synced" for e in body["events"])

    calendar = _only_calendar(fake_google)
    assert calendar.summary == "Prayers"
    assert calendar.time_zone == "America/Toronto"
    events = fake_google.live_events(calendar.id)
    assert [e["summary"] for e in events] == [
        "Fajr at home", "Dhuhr at home", "Asr at home", "Maghrib at home", "Isha at home"
    ]


def test_event_times_match_the_calculator_and_last_15_minutes(signed_in, fake_google):
    signed_in.post("/prayers/today")
    expected = calculate_prayer_times(OTTAWA["latitude"], OTTAWA["longitude"], DAY, OTTAWA["timezone"])

    events = fake_google.live_events(_only_calendar(fake_google).id)
    for event, name in zip(events, ["fajr", "dhuhr", "asr", "maghrib", "isha"]):
        start = datetime.fromisoformat(event["start"]["dateTime"])
        end = datetime.fromisoformat(event["end"]["dateTime"])
        assert start == getattr(expected, name).time
        assert end - start == timedelta(minutes=15)
        assert event["start"]["timeZone"] == "America/Toronto"


def test_description_says_where_the_time_came_from(signed_in, fake_google, db):
    signed_in.post("/prayers/today")

    events = fake_google.live_events(_only_calendar(fake_google).id)
    first_lines = [e["description"].splitlines()[0] for e in events]
    # Always ISNA with standard Asr. There's no setting for the method.
    assert first_lines == ["Calculated (ISNA, standard Asr)"] * 5


def test_first_run_says_isna_standard(signed_in, fake_google):
    response = signed_in.post("/prayers/today")

    assert response.json()["events"][0]["source"] == "Calculated (ISNA, standard Asr)"


def test_high_latitude_rule_is_named_in_the_description(client, fake_google, set_today, db):
    # Edmonton is above 48 degrees, so Isha in June uses the seventh of the night rule.
    sign_in(client, fake_google)
    save_setup(db, location=(53.5461, -113.4938), time_zone="America/Edmonton")
    set_today(date(2026, 6, 21), "America/Edmonton")

    response = client.post("/prayers/today")

    isha = response.json()["events"][-1]
    assert isha["source"] == "Calculated (ISNA, standard Asr, seventh of the night rule)"


def test_each_event_is_tagged_with_the_app_event_id(signed_in, fake_google, db):
    signed_in.post("/prayers/today")

    with DbSession(db) as session:
        rows = {row.id.hex: str(row.id) for row in session.scalars(select(PrayerEvent))}
    events = fake_google.live_events(_only_calendar(fake_google).id)
    for event in events:
        assert event["extendedProperties"]["private"]["appEventId"] == rows[event["id"]]


def test_running_twice_makes_no_duplicates(signed_in, fake_google, db):
    signed_in.post("/prayers/today")
    second = signed_in.post("/prayers/today")

    assert second.status_code == 200
    assert len(fake_google.live_events(_only_calendar(fake_google).id)) == 5
    with DbSession(db) as session:
        assert len(session.scalars(select(PrayerEvent)).all()) == 5
    # Nothing changed, so the second run sent Google nothing at all.
    assert [r.method for r in fake_google.writes()] == ["POST"] + ["POST"] * 5


def test_running_again_after_moving_updates_the_same_events(signed_in, fake_google, db):
    first = signed_in.post("/prayers/today").json()
    save_setup(db, location=MONTREAL)
    second = signed_in.post("/prayers/today").json()

    assert [e["app_event_id"] for e in first["events"]] == [e["app_event_id"] for e in second["events"]]
    assert second["events"][2]["starts_at"] < first["events"][2]["starts_at"]  # Montreal is further east


@pytest.mark.parametrize("failure", ["timeout", 429, 500, 503, "timeout_after_write"])
def test_google_failing_partway_leaves_no_duplicates(signed_in, fake_google, db, failure):
    # The 3rd event write (Asr) fails.
    fake_google.fail_event_write = {3: failure}

    response = signed_in.post("/prayers/today")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["saved"] == ["fajr", "dhuhr"]
    assert detail["waiting"] == ["asr", "maghrib", "isha"]
    with DbSession(db) as session:
        statuses = {r.prayer: r.sync_status for r in session.scalars(select(PrayerEvent))}
    assert statuses == {
        "fajr": "synced", "dhuhr": "synced", "asr": "pending", "maghrib": "pending", "isha": "pending"
    }

    # Running it again finishes the job, with exactly 5 events.
    again = signed_in.post("/prayers/today")

    assert again.status_code == 200
    events = fake_google.live_events(_only_calendar(fake_google).id)
    assert sorted(e["summary"] for e in events) == [
        "Asr at home", "Dhuhr at home", "Fajr at home", "Isha at home", "Maghrib at home"
    ]


def test_failing_every_time_never_duplicates(signed_in, fake_google):
    for attempt in range(1, 6):
        fake_google.fail_event_write = {fake_google._event_writes + attempt: "timeout_after_write"}
        signed_in.post("/prayers/today")

    signed_in.post("/prayers/today")
    assert len(fake_google.live_events(_only_calendar(fake_google).id)) == 5


def test_only_the_prayers_calendar_is_ever_written(signed_in, fake_google):
    fake_google.fail_event_write = {2: "timeout_after_write"}
    signed_in.post("/prayers/today")
    signed_in.post("/prayers/today")
    signed_in.post("/prayers/today")

    prayers_id = _only_calendar(fake_google).id
    for write in fake_google.writes():
        is_create_calendar = write.method == "POST" and write.path == "/calendar/v3/calendars"
        is_prayers_event = write.path.startswith(f"/calendar/v3/calendars/{prayers_id}/events")
        assert is_create_calendar or is_prayers_event, write.path
    # Only one calendar was ever created.
    assert sum(1 for w in fake_google.writes() if w.path == "/calendar/v3/calendars") == 1


def test_expired_access_token_is_refreshed_and_the_run_works(signed_in, fake_google, db):
    with DbSession(db) as session:
        session.execute(update(GoogleToken).values(access_token_expires_at=datetime(2000, 1, 1)))
        session.commit()

    response = signed_in.post("/prayers/today")

    assert response.status_code == 200
    assert fake_google.token_requests[-1]["grant_type"] == "refresh_token"


def test_token_rejected_by_google_is_refreshed_once(signed_in, fake_google):
    # Our saved expiry says it's fine, but Google says it isn't.
    fake_google.expire_access_tokens()

    response = signed_in.post("/prayers/today")

    assert response.status_code == 200
    assert len(fake_google.live_events(_only_calendar(fake_google).id)) == 5


def test_dead_refresh_token_asks_to_sign_in_again_without_crashing(signed_in, fake_google, db):
    fake_google.expire_access_tokens()
    fake_google.kill_refresh_tokens("user-a")

    response = signed_in.post("/prayers/today")

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "message": "Google sign-in expired. Sign in again.",
        "reason": "google_sign_in_expired",
        "login_url": "/auth/google/login",
    }
    # Google rejected the old token, so nothing was created.
    assert fake_google.calendars == {}
    # Signing in again and rerunning finishes the job.
    sign_in(signed_in, fake_google)
    assert signed_in.post("/prayers/today").status_code == 200
    assert len(fake_google.live_events(_only_calendar(fake_google).id)) == 5


def test_missing_calendar_access_is_reported(client, fake_google, set_today, db):
    sign_in(client, fake_google, scopes="openid https://www.googleapis.com/auth/userinfo.email")
    save_setup(db)
    set_today(DAY)

    response = client.post("/prayers/today")

    assert response.status_code == 403
    assert "allow calendar access" in response.json()["detail"]["message"]
    assert fake_google.writes() == []


def test_needs_sign_in(client):
    assert client.post("/prayers/today").status_code == 401


def test_needs_setup_first(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)

    response = client.post("/prayers/today")

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "Finish setup first."
    assert fake_google.writes() == []


def test_deleted_event_comes_back_exactly_once_when_it_changes(signed_in, fake_google, db):
    signed_in.post("/prayers/today")
    calendar = _only_calendar(fake_google)
    asr_id = fake_google.live_events(calendar.id)[2]["id"]
    fake_google.delete_event(calendar.id, asr_id)
    assert len(fake_google.live_events(calendar.id)) == 4

    # Unchanged events aren't sent again, so noticing deletions made in
    # Google waits for two-way sync (milestone 6). A change sends it back.
    save_setup(db, location=MONTREAL)
    signed_in.post("/prayers/today")

    events = fake_google.live_events(calendar.id)
    assert len(events) == 5
    assert [e["id"] for e in events].count(asr_id) == 1


def test_today_is_the_date_in_the_saved_time_zone(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    save_setup(db)
    # Noon on Oct 25 in Tokyo is 11 pm on Oct 24 in Toronto.
    set_today(date(2026, 10, 25), "Asia/Tokyo")

    response = client.post("/prayers/today")

    assert response.json()["date"] == "2026-10-24"
