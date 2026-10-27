"""Drive blocks: leave and arrival times, stable IDs, deletes, colours, reminders, and privacy.

KMA's made-up MAWAQIT page has Isha iqamah at 20:15 and Dhuhr iqamah at
13:00. The fake OpenRouteService says every drive is 14 minutes.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.event_plan import drive_event_id
from app.event_times import trip
from app.models import UserSettings, WeeklyMasjidPrayers
from app.prayer_sync import NotADriveBlock, delete_drive_block
from tests.calendar_helpers import clock, fetch, google_events, on, refresh, rows, titled
from tests.masjid_helpers import add_user, link, masjid_id

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=TORONTO)  # Sunday
MONDAY = date(2026, 10, 26)


def set_settings(db, user, **values):
    with Session(db) as session:
        row = session.query(UserSettings).filter_by(user_id=user).one()
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


@pytest.fixture
def user(db, fake_google, fake_mawaqit, ors_key):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={day: {"dhuhr", "isha"} for day in range(5)})
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    return uid


@pytest.fixture
def fetched(db, http, user):
    fetch(db, http, NOW)
    return user


def test_the_example_from_the_plan(db, http, fetched, fake_google):
    # Isha iqamah 8:15 pm, 5 minutes early, 14 minute drive.
    set_settings(db, fetched, arrive_early_minutes=5)
    refresh(db, http, fetched, NOW)
    events = google_events(fake_google)
    isha = titled(events, MONDAY, "Isha at KMA")
    assert [e["summary"] for e in on(events, MONDAY)] == [
        "Fajr", "Drive to KMA", "Dhuhr at KMA", "Asr", "Maghrib", "Drive to KMA", "Isha at KMA",
    ]
    evening = [e for e in on(events, MONDAY) if e["summary"] == "Drive to KMA"][1]
    assert (clock(evening), clock(evening, end=True)) == ("19:56", "20:10")
    assert (clock(isha), clock(isha, end=True)) == ("20:15", "20:30")
    assert "description" not in evening


@pytest.mark.parametrize("early, leave, arrive", [(0, "20:01", "20:15"), (30, "19:31", "19:45")])
def test_0_and_30_minutes_early(db, http, fetched, fake_google, early, leave, arrive):
    set_settings(db, fetched, arrive_early_minutes=early)
    refresh(db, http, fetched, NOW)
    evening = [e for e in on(google_events(fake_google), MONDAY) if e["summary"] == "Drive to KMA"][1]
    assert (clock(evening), clock(evening, end=True)) == (leave, arrive)
    assert clock(titled(google_events(fake_google), MONDAY, "Isha at KMA")) == "20:15"


def test_without_iqamah_the_target_is_the_calculated_start(db, http, user, fake_google):
    # Not fetched, so there's no iqamah at all.
    set_settings(db, user, arrive_early_minutes=10)
    refresh(db, http, user, NOW)
    events = on(google_events(fake_google), MONDAY)
    isha = next(e for e in events if e["summary"] == "Isha at KMA")
    drive = events[events.index(isha) - 1]
    start = datetime.fromisoformat(isha["start"]["dateTime"])
    assert datetime.fromisoformat(drive["end"]["dateTime"]) == start - timedelta(minutes=10)
    assert datetime.fromisoformat(drive["start"]["dateTime"]) == (start - timedelta(minutes=24)).replace(second=0)
    assert "description" not in drive


def test_no_drive_block_for_home_prayers_or_unknown_drive_times(db, http, fetched, fake_google, fake_ors):
    fake_ors.failure = "no_route"
    refresh(db, http, fetched, NOW)
    events = google_events(fake_google)
    assert not [e for e in events if e["summary"].startswith("Drive")]
    assert titled(events, MONDAY, "Isha at KMA")


def test_no_drive_block_without_a_key(db, http, fake_google, fake_mawaqit, monkeypatch):
    from app.config import get_ors_settings

    monkeypatch.setenv("ORS_API_KEY", "")
    get_ors_settings.cache_clear()
    uid = add_user(fake_google, db, "user-a", masjid_name="KMA", at_masjid={0: {"isha"}})
    refresh(db, http, uid, NOW)
    assert not [e for e in google_events(fake_google) if e["summary"].startswith("Drive")]


def test_drive_blocks_have_stable_ids_and_never_duplicate(db, http, fetched, fake_google, fake_ors):
    refresh(db, http, fetched, NOW)
    writes = len(fake_google.writes())
    refresh(db, http, fetched, NOW + timedelta(minutes=1))
    assert len(fake_google.writes()) == writes  # nothing changed, nothing sent
    saved = rows(db, fetched)
    prayers = {(r.local_date, r.prayer): r for r in saved if r.kind == "prayer"}
    drives = [r for r in saved if r.kind == "drive"]
    assert len(drives) == 20  # Dhuhr and Isha on 10 weekdays
    for drive in drives:
        assert drive.id == drive_event_id(prayers[(drive.local_date, drive.prayer)].id)
    ids = [e["id"] for e in google_events(fake_google)]
    assert len(ids) == len(set(ids))
    assert {d.id.hex for d in drives} <= set(ids)
    # Only one ORS call for the one masjid.
    assert len(fake_ors.requests) == 1


def test_no_reminders_until_the_user_picks_one(db, http, fetched, fake_google):
    # The "before leaving" setting starts at "No notification" (see test_reminders.py).
    refresh(db, http, fetched, NOW)
    events = google_events(fake_google)
    assert all(e["reminders"] == {"useDefault": False, "overrides": []} for e in events)
    assert all("colorId" not in e for e in events)  # no colour picked: the calendar's colour


def test_colours_go_on_the_right_blocks(db, http, fetched, fake_google):
    set_settings(db, fetched, prayer_color_id="7", drive_color_id="11")
    refresh(db, http, fetched, NOW)
    for event in google_events(fake_google):
        assert event["colorId"] == ("11" if event["summary"].startswith("Drive") else "7")


def test_changing_how_early_updates_only_drive_blocks(db, http, fetched, fake_google):
    refresh(db, http, fetched, NOW)
    before = len(fake_google.writes())
    set_settings(db, fetched, arrive_early_minutes=10)
    refresh(db, http, fetched, NOW)
    changed = fake_google.writes()[before:]
    # 2 masjid prayers a weekday for 2 weeks, but the coming Friday's Dhuhr is
    # Jumuah, which has its own "how early": 19 drive blocks.
    assert len(changed) == 19
    assert {w.body["summary"] for w in changed} == {"Drive to KMA"}


def test_changing_a_colour_updates_only_those_blocks(db, http, fetched, fake_google):
    refresh(db, http, fetched, NOW)
    before = len(fake_google.writes())
    set_settings(db, fetched, drive_color_id="5")
    refresh(db, http, fetched, NOW)
    changed = fake_google.writes()[before:]
    assert {w.body["summary"] for w in changed} == {"Drive to KMA"}
    before = len(fake_google.writes())
    set_settings(db, fetched, prayer_color_id="2")
    refresh(db, http, fetched, NOW)
    changed = fake_google.writes()[before:]
    # Every prayer block, 5 a day for 14 days, except today's Fajr: it's in the past.
    assert len(changed) == 69
    assert all(not w.body["summary"].startswith("Drive") for w in changed)


def test_switching_a_prayer_home_deletes_only_its_future_drive_block(db, http, fetched, fake_google):
    monday_noon = datetime(2026, 10, 26, 13, 30, tzinfo=TORONTO)  # Monday's Dhuhr drive has passed
    refresh(db, http, fetched, NOW)
    before_ids = {e["id"] for e in google_events(fake_google)}
    # Monday: Dhuhr and Isha move home.
    with Session(db) as session:
        monday = session.query(WeeklyMasjidPrayers).filter_by(user_id=fetched, weekday=0).one()
        monday.dhuhr = monday.isha = False
        session.commit()
    refresh(db, http, fetched, monday_noon)

    deletes = fake_google.deletes()
    saved = {r.id.hex: r for r in rows(db, fetched)}
    deleted = [saved[d.path.rsplit("/", 1)[1]] for d in deletes]
    # Monday Nov 2 lost both drives. Monday Oct 26: Isha's drive is still ahead, Dhuhr's is past.
    assert sorted((r.local_date, r.prayer) for r in deleted) == [
        (date(2026, 10, 26), "isha"), (date(2026, 11, 2), "dhuhr"), (date(2026, 11, 2), "isha"),
    ]
    assert all(r.kind == "drive" for r in deleted)
    live = {e["id"]: e for e in google_events(fake_google)}
    past_drive = next(r for r in rows(db, fetched) if r.kind == "drive" and r.local_date == MONDAY and r.prayer == "dhuhr")
    assert past_drive.id.hex in live  # past events are never touched
    # Every prayer block is still there.
    assert {r.id.hex for r in rows(db, fetched) if r.kind == "prayer"} <= set(live)
    assert before_ids - set(live) == {r.id.hex for r in deleted}
    assert titled(list(live.values()), date(2026, 11, 2), "Isha")


def test_a_deleted_drive_block_comes_back_when_needed(db, http, fetched, fake_google, fake_ors):
    refresh(db, http, fetched, NOW)
    fake_ors.failure = "timeout"
    with Session(db) as session:
        from app.models import UserDriveTime

        session.query(UserDriveTime).delete()
        session.commit()
    refresh(db, http, fetched, NOW)  # the drive time is unknown now
    assert len(fake_google.deletes()) == 20
    assert not [e for e in google_events(fake_google) if e["summary"].startswith("Drive")]
    fake_ors.failure = None
    refresh(db, http, fetched, NOW)
    drives = [e for e in google_events(fake_google) if e["summary"].startswith("Drive")]
    assert len(drives) == 20
    assert len({e["id"] for e in drives}) == 20


def test_only_future_drive_blocks_can_be_deleted(db, http, fetched):
    refresh(db, http, fetched, NOW)
    saved = rows(db, fetched)
    prayer = next(r for r in saved if r.kind == "prayer" and r.starts_at > NOW)
    drive = next(r for r in saved if r.kind == "drive")
    with pytest.raises(NotADriveBlock):
        delete_drive_block(None, prayer.google_calendar_id, prayer, NOW)
    with pytest.raises(NotADriveBlock):
        delete_drive_block(None, drive.google_calendar_id, drive, drive.starts_at + timedelta(minutes=1))


@pytest.mark.parametrize(
    "target, drive, leave",
    [
        # Fall back: 1:05 am EST is 30 minutes after 1:35 am EDT.
        (datetime(2026, 11, 1, 1, 5, fold=1, tzinfo=TORONTO), 30 * 60, "2026-11-01T01:35:00-04:00"),
        # Spring forward: 3:10 am EDT minus 20 minutes is 1:50 am EST.
        (datetime(2026, 3, 8, 3, 10, tzinfo=TORONTO), 20 * 60, "2026-03-08T01:50:00-05:00"),
        # A normal Fajr on the fall day.
        (datetime(2026, 11, 1, 6, 0, tzinfo=TORONTO), 14 * 60, "2026-11-01T05:46:00-05:00"),
    ],
)
def test_leave_times_across_daylight_saving(target, drive, leave):
    assert trip(target, 0, drive).leave_at.isoformat() == leave


def test_every_event_is_private(db, http, fetched, fake_google):
    refresh(db, http, fetched, NOW)
    events = google_events(fake_google)
    assert {e["summary"].split()[0] for e in events} >= {"Drive", "Isha", "Fajr"}
    assert all(e["visibility"] == "private" for e in events)


def test_commute_blocks_are_renamed_and_made_private_in_place(db, http, fetched, fake_google, monkeypatch):
    from app import prayer_sync

    # Made by an earlier version of this branch: "Commute to KMA", and events weren't private.
    real_event = prayer_sync.google_event

    def old_event(row):
        body = real_event(row)
        body.pop("visibility")
        body["summary"] = body["summary"].replace("Drive to", "Commute to")
        return body

    monkeypatch.setattr(prayer_sync, "google_event", old_event)
    refresh(db, http, fetched, NOW)
    old = {e["id"]: e for e in google_events(fake_google)}
    assert any(e["summary"] == "Commute to KMA" for e in old.values())
    monkeypatch.setattr(prayer_sync, "google_event", real_event)
    before = len(fake_google.writes())

    later = datetime(2026, 10, 25, 13, 30, tzinfo=TORONTO)  # the same Sunday, after Dhuhr
    refresh(db, http, fetched, later)
    changed = fake_google.writes()[before:]

    # The same IDs, so nothing is duplicated, and no inserts at all.
    new = {e["id"]: e for e in google_events(fake_google)}
    assert set(new) == set(old)
    assert {w.method for w in changed} == {"PUT"}
    # Every future event became private, and commute blocks became drive blocks.
    future = [e for e in new.values() if datetime.fromisoformat(e["start"]["dateTime"]) > later]
    assert future and all(e["visibility"] == "private" for e in future)
    assert not [e for e in future if e["summary"].startswith("Commute")]
    assert any(e["summary"] == "Drive to KMA" for e in future)
    # Past events weren't touched.
    past = [e for e in new.values() if datetime.fromisoformat(e["start"]["dateTime"]) <= later]
    assert past and all("visibility" not in e for e in past)
    assert len(changed) == len(future)


def test_old_15_minute_blocks_are_shortened_in_place(db, http, fetched, fake_google, monkeypatch):
    from app.prayer_sync import PRAYER_LENGTHS

    # Before this change, every prayer block was 15 minutes.
    for name in PRAYER_LENGTHS:
        monkeypatch.setitem(PRAYER_LENGTHS, name, timedelta(minutes=15))
    refresh(db, http, fetched, NOW)
    old = {e["id"]: e for e in google_events(fake_google)}
    monkeypatch.undo()
    before = len(fake_google.writes())

    later = datetime(2026, 10, 25, 13, 30, tzinfo=TORONTO)  # the same Sunday, after Dhuhr
    refresh(db, http, fetched, later)
    changed = fake_google.writes()[before:]

    # Updated in place, and only future Fajr, Asr, and Maghrib blocks changed.
    assert {e["id"] for e in google_events(fake_google)} == set(old)
    assert {w.method for w in changed} == {"PUT"}
    assert {w.body["summary"].split()[0] for w in changed} == {"Fajr", "Asr", "Maghrib"}
    assert all(datetime.fromisoformat(w.body["start"]["dateTime"]) > later for w in changed)
    asr = titled(google_events(fake_google), MONDAY, "Asr")
    assert (datetime.fromisoformat(asr["end"]["dateTime"]) - datetime.fromisoformat(asr["start"]["dateTime"])) == timedelta(minutes=10)


def test_old_at_home_titles_are_renamed_in_place(db, http, fetched, fake_google, monkeypatch):
    from app import prayer_sync

    # Before this change, home prayers were "Fajr at home". Masjid prayers keep "Dhuhr at KMA".
    real_event = prayer_sync.google_event

    def old_event(row):
        body = real_event(row)
        if body["summary"] in ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"):
            body["summary"] += " at home"
        return body

    monkeypatch.setattr(prayer_sync, "google_event", old_event)
    refresh(db, http, fetched, NOW)
    old = {e["id"]: e for e in google_events(fake_google)}
    assert titled(list(old.values()), MONDAY, "Fajr at home")
    monkeypatch.setattr(prayer_sync, "google_event", real_event)
    before = len(fake_google.writes())

    later = datetime(2026, 10, 25, 13, 30, tzinfo=TORONTO)  # the same Sunday, after Dhuhr
    refresh(db, http, fetched, later)
    changed = fake_google.writes()[before:]

    # The same IDs, updated in place: only future home prayers, now just the prayer's name.
    new = {e["id"]: e for e in google_events(fake_google)}
    assert set(new) == set(old)
    assert {w.method for w in changed} == {"PUT"}
    assert {w.body["summary"] for w in changed} == {"Fajr", "Asr", "Maghrib", "Dhuhr", "Isha"}
    assert all(datetime.fromisoformat(w.body["start"]["dateTime"]) > later for w in changed)
    monday = [e["summary"] for e in on(google_events(fake_google), MONDAY)]
    assert monday == ["Fajr", "Drive to KMA", "Dhuhr at KMA", "Asr", "Maghrib", "Drive to KMA", "Isha at KMA"]
    # Past events weren't touched, so this morning's Fajr keeps its old title.
    assert titled(list(new.values()), date(2026, 10, 25), "Fajr at home")


def test_old_descriptions_are_removed_in_place(db, http, fetched, fake_google, monkeypatch):
    from app import prayer_sync

    # Before this change, every event had a description, drive blocks too.
    real_event = prayer_sync.google_event

    def old_event(row):
        return {**real_event(row), "description": "KMA iqamah (MAWAQIT, updated Oct 25, 2026)"}

    monkeypatch.setattr(prayer_sync, "google_event", old_event)
    refresh(db, http, fetched, NOW)
    old = {e["id"]: e for e in google_events(fake_google)}
    assert all("description" in e for e in old.values())
    monkeypatch.setattr(prayer_sync, "google_event", real_event)
    before = len(fake_google.writes())

    later = datetime(2026, 10, 25, 13, 30, tzinfo=TORONTO)  # the same Sunday, after Dhuhr
    refresh(db, http, fetched, later)
    changed = fake_google.writes()[before:]

    # The same IDs, updated in place, and only future events.
    new = {e["id"]: e for e in google_events(fake_google)}
    assert set(new) == set(old)
    assert {w.method for w in changed} == {"PUT"}
    assert all(datetime.fromisoformat(w.body["start"]["dateTime"]) > later for w in changed)
    assert not any("description" in e for e in new.values() if datetime.fromisoformat(e["start"]["dateTime"]) > later)
    # This morning's Fajr already happened, so it keeps its old description.
    assert "description" in titled(list(new.values()), date(2026, 10, 25), "Fajr")
