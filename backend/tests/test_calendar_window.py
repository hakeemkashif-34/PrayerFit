"""Tests for filling and updating the 14-day window in Google Calendar."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import PrayerEvent
from tests.conftest import sign_in
from tests.setup_helpers import save_setup, setup_through_api

DAY = date(2026, 10, 24)  # a Saturday
TORONTO = ZoneInfo("America/Toronto")
IQAMAH_NOTE = "Iqamah times not added yet, so this is the calculated prayer time."


@pytest.fixture
def signed_in(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    return client


def _events(fake_google) -> list[dict]:
    return fake_google.live_events(fake_google.calendars_of("user-a")[0].id)


def _local_start(event: dict) -> datetime:
    return datetime.fromisoformat(event["start"]["dateTime"])


def _rows(db) -> list[PrayerEvent]:
    with DbSession(db) as session:
        return list(session.scalars(select(PrayerEvent)))


# ---- The first fill ----


def test_fill_makes_70_events_with_no_duplicates(signed_in, fake_osm, fake_google, db):
    setup_through_api(signed_in, fake_osm)

    events = _events(fake_google)
    assert len(events) == 70
    assert len({e["id"] for e in events}) == 70
    rows = _rows(db)
    assert len(rows) == 70
    assert len({(r.local_date, r.prayer) for r in rows}) == 70
    # Today plus the next 13 days, 5 prayers each.
    dates = sorted({r.local_date for r in rows})
    assert dates == [DAY + timedelta(days=n) for n in range(14)]
    assert all(r.sync_status == "synced" for r in rows)


def test_titles_say_home_or_the_masjid(signed_in, fake_osm, fake_google):
    # Default in the helper: Dhuhr and Isha at the masjid, Monday to Friday.
    setup_through_api(signed_in, fake_osm)

    titles = {(_local_start(e).date(), e["summary"]) for e in _events(fake_google)}
    monday = date(2026, 10, 26)
    assert (monday, "Fajr at home") in titles
    assert (monday, "Dhuhr at KMA") in titles
    assert (monday, "Asr at home") in titles
    assert (monday, "Isha at KMA") in titles
    assert (DAY, "Dhuhr at home") in titles  # Saturday isn't ticked
    assert sum(t.endswith("at KMA") for _, t in titles) == 20  # 10 weekdays x 2


def test_without_a_short_name_the_title_uses_the_full_name(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm, short_name=None)

    titles = {e["summary"] for e in _events(fake_google)}
    assert "Dhuhr at Kanata Muslim Association" in titles


def test_masjid_events_say_the_time_is_calculated(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm)

    for event in _events(fake_google):
        if event["summary"].endswith("at KMA"):
            assert IQAMAH_NOTE in event["description"]
        else:
            assert IQAMAH_NOTE not in event["description"]
        # Every event says where its time came from.
        assert event["description"].startswith("Calculated (ISNA, standard Asr)")


def test_dhuhr_description_explains_the_extra_minute(signed_in, fake_google, db):
    # Ottawa on October 24, 2026: solar noon is 12:46:57, so Dhuhr is 12:48.
    save_setup(db)

    signed_in.post("/calendar/sync")

    dhuhr = next(
        e for e in _events(fake_google)
        if e["summary"] == "Dhuhr at home" and _local_start(e).date() == DAY
    )
    assert _local_start(dhuhr).strftime("%H:%M") == "12:48"
    assert dhuhr["description"].splitlines() == [
        "Calculated (ISNA, standard Asr)",
        "Starts 1 minute after solar noon (12:46:57 pm), once the whole sun has passed "
        "overhead, then rounded up to the minute.",
    ]


def test_umm_al_qura_dhuhr_is_at_solar_noon(signed_in, fake_google, db):
    save_setup(db, method="umm_al_qura")

    signed_in.post("/calendar/sync")

    dhuhr = next(e for e in _events(fake_google) if e["summary"] == "Dhuhr at home")
    assert dhuhr["description"].splitlines()[-1] == (
        "Starts at solar noon (12:46:57 pm), rounded up to the minute."
    )


# ---- Changes after setup ----


def test_a_change_only_sends_the_events_that_changed(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm)
    writes_before = len(fake_google.writes())

    # Tick Asr at the masjid on Tuesdays.
    settings = signed_in.get("/settings").json()
    days = settings["weekly"]
    days[1]["asr"] = True
    response = signed_in.put("/settings/weekly", json={"days": days})

    # 2 Tuesdays in the window (Oct 27 and Nov 3), 1 Asr each.
    assert response.json()["calendar"]["status"] == "updated"
    assert response.json()["calendar"]["sent"] == 2
    new_writes = fake_google.writes()[writes_before:]
    assert [w.method for w in new_writes] == ["PUT", "PUT"]
    assert [w.body["summary"] for w in new_writes] == ["Asr at KMA", "Asr at KMA"]
    assert [_local_start(w.body).date() for w in new_writes] == [date(2026, 10, 27), date(2026, 11, 3)]
    assert len(_events(fake_google)) == 70


def test_past_events_are_left_alone(signed_in, fake_osm, fake_google, db):
    setup_through_api(signed_in, fake_osm)
    fajr_before = next(
        e for e in _events(fake_google) if _local_start(e).date() == DAY and e["summary"].startswith("Fajr")
    )

    # It's noon, so today's Fajr has passed. Every other event changes.
    response = signed_in.put("/settings/methods", json={"asr_method": "hanafi"})

    assert response.json()["calendar"]["sent"] == 69
    fajr_after = next(e for e in _events(fake_google) if e["id"] == fajr_before["id"])
    assert fajr_after == fajr_before
    sent_ids = {w.path.rsplit("/", 1)[-1] for w in fake_google.writes() if w.method == "PUT"}
    assert fajr_before["id"] not in sent_ids


def test_nothing_changed_means_nothing_sent(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm)
    writes_before = len(fake_google.writes())

    response = signed_in.post("/calendar/sync")

    assert response.json() == {
        "status": "updated", "sent": 0, "waiting": 0, "message": "Calendar updated. 0 events sent to Google."
    }
    assert len(fake_google.writes()) == writes_before


def test_saving_the_same_answer_sends_nothing(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm)
    writes_before = len(fake_google.writes())

    signed_in.put("/settings/methods", json={})

    assert len(fake_google.writes()) == writes_before


def test_switching_to_home_renames_the_masjid_events(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm)

    response = signed_in.put("/settings/main-masjid", json={"choice": "home"})

    assert response.json()["calendar"]["sent"] == 20
    assert all(e["summary"].endswith("at home") for e in _events(fake_google))


def test_moving_updates_the_calendar_and_event_time_zones(signed_in, fake_osm, fake_google):
    setup_through_api(signed_in, fake_osm)
    fake_osm.add_place(49.2827, -123.1207, name="Robson Street", city="Vancouver", country="Canada")

    signed_in.put("/settings/location", json={"query": "Robson Street", "index": 0})

    calendar = fake_google.calendars_of("user-a")[0]
    assert calendar.time_zone == "America/Vancouver"
    future = [e for e in _events(fake_google) if _local_start(e).date() > DAY]
    assert {e["start"]["timeZone"] for e in future} == {"America/Vancouver"}


# ---- Google failing ----


def test_google_failing_partway_finishes_later_without_duplicates(signed_in, fake_osm, fake_google, db):
    fake_google.fail_event_write = {30: 503}

    response = setup_through_api(signed_in, fake_osm)

    calendar = response.json()["calendar"]
    assert calendar["status"] == "waiting"
    assert (calendar["sent"], calendar["waiting"]) == (29, 41)
    assert len(_events(fake_google)) == 29

    again = signed_in.post("/calendar/sync")

    assert again.json()["status"] == "updated"
    assert again.json()["sent"] == 41
    assert len(_events(fake_google)) == 70
    assert all(r.sync_status == "synced" for r in _rows(db))


def test_timeout_after_google_saved_it_makes_no_duplicate(signed_in, fake_osm, fake_google):
    fake_google.fail_event_write = {10: "timeout_after_write"}

    setup_through_api(signed_in, fake_osm)
    signed_in.post("/calendar/sync")

    events = _events(fake_google)
    assert len(events) == 70
    assert len({e["id"] for e in events}) == 70


# ---- Rolling forward ----


def test_next_day_adds_one_new_day_and_keeps_the_old_one(signed_in, fake_osm, fake_google, set_today):
    setup_through_api(signed_in, fake_osm)

    set_today(DAY + timedelta(days=1))
    response = signed_in.post("/calendar/sync")

    assert response.json()["sent"] == 5  # only the new day, November 7
    events = _events(fake_google)
    assert len(events) == 75  # yesterday's prayers stay in Google
    assert max(_local_start(e).date() for e in events) == date(2026, 11, 7)
    assert not [w for w in fake_google.requests if w.method == "DELETE"]
