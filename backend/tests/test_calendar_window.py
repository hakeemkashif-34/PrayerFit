"""Tests for filling and updating the 14-day window in Google Calendar."""

import logging
import re
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
IQAMAH_NOTE = "KMA's iqamah time isn't available."


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


def test_fill_makes_70_events_with_no_duplicates(signed_in, fake_photon, fake_google, db):
    setup_through_api(signed_in, fake_photon)

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


def test_titles_say_home_or_the_masjid(signed_in, fake_photon, fake_google):
    # Default in the helper: Dhuhr and Isha at the masjid, Monday to Friday.
    setup_through_api(signed_in, fake_photon)

    titles = {(_local_start(e).date(), e["summary"]) for e in _events(fake_google)}
    monday = date(2026, 10, 26)
    assert (monday, "Fajr") in titles
    assert (monday, "Dhuhr at KMA") in titles
    assert (monday, "Asr") in titles
    assert (monday, "Isha at KMA") in titles
    assert (DAY, "Dhuhr") in titles  # Saturday isn't ticked
    assert sum(t.endswith("at KMA") for _, t in titles) == 20  # 10 weekdays x 2


def test_without_a_short_name_the_title_uses_the_full_name(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon, short_name=None)

    titles = {e["summary"] for e in _events(fake_google)}
    assert "Dhuhr at Kanata Muslim Association" in titles


def test_masjid_events_say_the_time_is_calculated(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon)

    for event in _events(fake_google):
        # Every event says where its time came from.
        if event["summary"].endswith("at KMA"):
            assert event["description"].startswith(f"Calculated start time (ISNA, standard Asr). {IQAMAH_NOTE}")
        else:
            assert IQAMAH_NOTE not in event["description"]
            assert event["description"].startswith("Calculated (ISNA, standard Asr)")


def test_dhuhr_description_explains_the_extra_minute(signed_in, fake_google, db):
    # Ottawa on October 24, 2026: solar noon is 12:46:57, so Dhuhr is 12:48.
    save_setup(db)

    signed_in.post("/calendar/sync")

    dhuhr = next(
        e for e in _events(fake_google)
        if e["summary"] == "Dhuhr" and _local_start(e).date() == DAY
    )
    assert _local_start(dhuhr).strftime("%H:%M") == "12:48"
    assert dhuhr["description"].splitlines() == [
        "Calculated (ISNA, standard Asr)",
        "Starts 1 minute after solar noon (12:46:57 pm), once the whole sun has passed "
        "overhead, then rounded up to the minute.",
    ]


# ---- Changes after setup ----


def test_a_change_only_sends_the_events_that_changed(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon)
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


def test_past_events_are_left_alone(signed_in, fake_photon, fake_google, db):
    setup_through_api(signed_in, fake_photon)
    fajr_before = next(
        e for e in _events(fake_google) if _local_start(e).date() == DAY and e["summary"].startswith("Fajr")
    )

    # It's noon, so today's Fajr has passed. A new prayer colour changes every other event.
    response = signed_in.put("/settings/optional", json={"short_name": "KMA", "prayer_color_id": "3"})

    assert response.json()["calendar"]["sent"] == 69
    fajr_after = next(e for e in _events(fake_google) if e["id"] == fajr_before["id"])
    assert fajr_after == fajr_before
    sent_ids = {w.path.rsplit("/", 1)[-1] for w in fake_google.writes() if w.method == "PUT"}
    assert fajr_before["id"] not in sent_ids


def test_nothing_changed_means_nothing_sent(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon)
    writes_before = len(fake_google.writes())

    response = signed_in.post("/calendar/sync")

    assert response.json() == {
        "status": "updated", "sent": 0, "waiting": 0, "message": "Calendar updated. 0 events sent to Google."
    }
    assert len(fake_google.writes()) == writes_before


def test_saving_the_same_answer_sends_nothing(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon)
    writes_before = len(fake_google.writes())

    # The same answers setup_through_api gave.
    signed_in.put("/settings/optional", json={"short_name": "KMA"})

    assert len(fake_google.writes()) == writes_before


def test_switching_to_home_renames_the_masjid_events(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon)

    response = signed_in.put("/settings/main-masjid", json={"choice": "home"})

    assert response.json()["calendar"]["sent"] == 20
    # Home prayers are just the prayer's name.
    assert {e["summary"] for e in _events(fake_google)} == {"Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"}


def test_moving_updates_the_calendar_and_event_time_zones(signed_in, fake_photon, fake_google):
    setup_through_api(signed_in, fake_photon)
    fake_photon.add_place(49.2827, -123.1207, name="Robson Street", city="Vancouver", country="Canada")

    signed_in.put("/settings/location", json={"query": "Robson Street", "index": 0})

    calendar = fake_google.calendars_of("user-a")[0]
    assert calendar.time_zone == "America/Vancouver"
    future = [e for e in _events(fake_google) if _local_start(e).date() > DAY]
    assert {e["start"]["timeZone"] for e in future} == {"America/Vancouver"}


# ---- Google failing ----


def test_google_failing_partway_finishes_later_without_duplicates(signed_in, fake_photon, fake_google, db):
    fake_google.fail_event_write = {30: 503}

    response = setup_through_api(signed_in, fake_photon)

    calendar = response.json()["calendar"]
    assert calendar["status"] == "waiting"
    assert (calendar["sent"], calendar["waiting"]) == (29, 41)
    assert len(_events(fake_google)) == 29

    again = signed_in.post("/calendar/sync")

    assert again.json()["status"] == "updated"
    assert again.json()["sent"] == 41
    assert len(_events(fake_google)) == 70
    assert all(r.sync_status == "synced" for r in _rows(db))


def test_google_failure_logs_the_reason_and_time_but_no_ids_or_address(signed_in, fake_photon, fake_google, caplog):
    fake_google.fail_event_write = {3: 503, 4: "timeout"}
    caplog.set_level(logging.DEBUG)

    setup_through_api(signed_in, fake_photon)  # stops at the 3rd write
    signed_in.post("/calendar/sync")  # the 1st write of this run times out

    assert re.search(r"Google Calendar (POST|PUT) failed: status 503 after \d+\.\d s", caplog.text)
    assert re.search(r"Google Calendar (POST|PUT) failed: timeout after \d+\.\d s", caplog.text)
    assert "group.calendar.google.com" not in caplog.text
    assert "Kanata" not in caplog.text


def test_timeout_after_google_saved_it_makes_no_duplicate(signed_in, fake_photon, fake_google):
    fake_google.fail_event_write = {10: "timeout_after_write"}

    setup_through_api(signed_in, fake_photon)
    signed_in.post("/calendar/sync")

    events = _events(fake_google)
    assert len(events) == 70
    assert len({e["id"] for e in events}) == 70


# ---- Rolling forward ----


def test_next_day_adds_one_new_day_and_keeps_the_old_one(signed_in, fake_photon, fake_google, set_today):
    setup_through_api(signed_in, fake_photon)

    set_today(DAY + timedelta(days=1))
    response = signed_in.post("/calendar/sync")

    assert response.json()["sent"] == 5  # only the new day, November 7
    events = _events(fake_google)
    assert len(events) == 75  # yesterday's prayers stay in Google
    assert max(_local_start(e).date() for e in events) == date(2026, 11, 7)
    assert not [w for w in fake_google.requests if w.method == "DELETE"]


def test_a_user_on_another_method_moves_to_isna_with_only_future_events_sent(signed_in, fake_google, db, monkeypatch):
    from app import user_settings
    from app.prayer_times import CalculationMethod

    # Before milestone 5, this user had MWL saved.
    save_setup(db)
    monkeypatch.setattr(user_settings, "DEFAULT_METHOD", CalculationMethod.MWL)
    signed_in.post("/calendar/sync")
    fajr_before = next(e for e in _events(fake_google) if _local_start(e).date() == DAY and e["summary"].startswith("Fajr"))
    assert fajr_before["description"].startswith("Calculated (MWL, standard Asr)")
    before = len(fake_google.writes())

    # Now every user is on ISNA. It's noon, so today's Fajr has passed and stays as it was.
    monkeypatch.setattr(user_settings, "DEFAULT_METHOD", CalculationMethod.ISNA)
    response = signed_in.post("/calendar/sync")

    changed = fake_google.writes()[before:]
    # Every description names the method, so every future event changes:
    # 70 minus today's Fajr, which is in the past.
    assert response.json()["sent"] == len(changed) == 69
    assert all(w.body["description"].startswith("Calculated (ISNA, standard Asr)") for w in changed)
    assert fajr_before["id"] not in {w.path.rsplit("/", 1)[-1] for w in changed}
