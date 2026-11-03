"""Google Calendar locations on masjid prayers.

A masjid prayer block gets the masjid's name and public address. Home,
moved, and clash prayers get none, and the user's home address is never in
any event. Uses the same made-up KMA week as test_moving_calendar.py:
Asr and Isha at KMA on Tuesdays, home is "1 Test Street, Ottawa".
"""

from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.event_plan import masjid_location
from app.models import Masjid, PrayerEvent, WeeklyMasjidPrayers
from app.prayer_sync import event_hash
from tests.calendar_helpers import google_events, on, refresh, rows, titled
from tests.masjid_helpers import masjid_id
from tests.test_moving_calendar import NOW, TORONTO, TUESDAY, busy, run, user  # noqa: F401

KMA_ADDRESS = "351 Sandhill Road, Ottawa"
KMA_LOCATION = f"Kanata Muslim Association, {KMA_ADDRESS}"
FRIDAY = date(2026, 10, 30)


@pytest.fixture
def kma_address(db, user):
    """The address OpenStreetMap gives KMA, saved on its masjid row."""
    with Session(db) as session:
        session.get(Masjid, masjid_id(db, "Kanata Muslim Association")).address = KMA_ADDRESS
        session.commit()


def event(fake_google, day: date, summary: str) -> dict:
    return titled(google_events(fake_google), day, summary)


def no_home_address(fake_google) -> None:
    for each in google_events(fake_google):
        assert "Test Street" not in each.get("location", "")
        assert "Test Street" not in each.get("description", "")


# ---- Which text ----


@pytest.mark.parametrize(
    "source, name, address, expected",
    [
        ("openstreetmap", "Kanata Muslim Association", KMA_ADDRESS, KMA_LOCATION),
        ("list", "Barrhaven Islamic Centre", "3971 Greenbank Road, Ottawa",
         "Barrhaven Islamic Centre, 3971 Greenbank Road, Ottawa"),
        # No postal code, even if one was saved.
        ("list", "Masjid ar-Rahmah", "1216 Hunt Club Rd., Ottawa, ON K1V 2P1", "Masjid ar-Rahmah, 1216 Hunt Club Rd., Ottawa, ON"),
        ("openstreetmap", "Masjid", "12 Main Street, Ottawa K2K2K2", "Masjid, 12 Main Street, Ottawa"),
        # No address saved (KMA from my list has none): just the name.
        ("list", "Kanata Muslim Association", None, "Kanata Muslim Association"),
        # A masjid on OpenStreetMap with no name: its public address.
        ("openstreetmap", None, "5 Masjid Road, Ottawa", "5 Masjid Road, Ottawa"),
        # Picked by typing an address: only what one user typed, so nothing.
        ("user", None, "20 Somewhere Crescent, Ottawa", None),
        ("user", "My masjid", "20 Somewhere Crescent, Ottawa", None),
    ],
)
def test_the_location_text(source, name, address, expected):
    assert masjid_location(Masjid(source=source, name=name, address=address, latitude=45.0, longitude=-75.0)) == expected


# ---- In the calendar ----


def test_masjid_prayers_get_the_masjids_name_and_address(db, http, user, kma_address, fake_google):
    run(db, http, user)
    assert event(fake_google, TUESDAY, "Asr at KMA")["location"] == KMA_LOCATION
    assert event(fake_google, TUESDAY, "Isha at KMA")["location"] == KMA_LOCATION
    # Prayers at home have no location.
    for name in ("Fajr", "Dhuhr", "Maghrib"):
        assert "location" not in event(fake_google, TUESDAY, name)
    # Drive blocks are unchanged for now: no location.
    assert all("location" not in e for e in on(google_events(fake_google), TUESDAY) if e["summary"] == "Drive to KMA")
    no_home_address(fake_google)


def test_jumuah_at_the_masjid_gets_its_location(db, http, user, kma_address, fake_google):
    run(db, http, user)
    assert event(fake_google, FRIDAY, "Jumuah at KMA")["location"] == KMA_LOCATION


def test_a_masjid_prayer_that_moves_loses_its_location(db, http, user, kma_address, fake_google):
    run(db, http, user)
    assert event(fake_google, TUESDAY, "Isha at KMA")["location"] == KMA_LOCATION
    # A class from 7 to 8:30 pm: Isha moves home, after the class.
    busy(fake_google, ("19:00", "20:30"))
    refresh(db, http, user, NOW.replace(hour=9))
    isha = event(fake_google, TUESDAY, "Isha")
    assert "location" not in isha
    # It was an update that replaced the whole event, so Google doesn't keep the old location.
    [put] = [r for r in fake_google.writes() if r.method == "PUT" and r.path.endswith(isha["id"])]
    assert "location" not in put.body
    no_home_address(fake_google)


def test_a_clash_has_no_location(db, http, user, kma_address, fake_google):
    run(db, http, user)
    # A class from 3 to 6:30 pm covers all of Asr's time.
    busy(fake_google, ("15:00", "18:30"))
    refresh(db, http, user, NOW.replace(hour=9))
    assert "location" not in event(fake_google, TUESDAY, "Asr (clash)")
    no_home_address(fake_google)


def set_tuesday_isha(db, uid, at_masjid: bool) -> None:
    with Session(db) as session:
        row = session.query(WeeklyMasjidPrayers).filter_by(user_id=uid, weekday=1).one()
        row.isha = at_masjid
        session.commit()


def test_the_location_follows_a_prayer_from_the_masjid_to_home_and_back(db, http, user, kma_address, fake_google):
    run(db, http, user)
    set_tuesday_isha(db, user, at_masjid=False)
    refresh(db, http, user, NOW.replace(hour=9))
    assert "location" not in event(fake_google, TUESDAY, "Isha")
    set_tuesday_isha(db, user, at_masjid=True)
    refresh(db, http, user, NOW.replace(hour=10))
    assert event(fake_google, TUESDAY, "Isha at KMA")["location"] == KMA_LOCATION


def test_existing_events_get_the_location_but_past_ones_are_left_alone(db, http, user, kma_address, fake_google):
    run(db, http, user)
    # Like the calendar before this change: masjid prayers saved and sent with no location.
    with Session(db) as session:
        for row in session.query(PrayerEvent).filter_by(user_id=user):
            row.location = None
            row.synced_hash = event_hash(row)
        session.commit()
    before = len(fake_google.writes())

    # Tuesday 5 pm: Asr at KMA (iqamah 4:15 pm) has started, so it's the past. Isha hasn't.
    refresh(db, http, user, datetime(2026, 10, 27, 17, 0, tzinfo=TORONTO))
    saved = {(r.local_date, r.prayer, r.kind): r for r in rows(db, user)}
    asr, isha = saved[(TUESDAY, "asr", "prayer")], saved[(TUESDAY, "isha", "prayer")]
    assert asr.location is None
    assert isha.location == KMA_LOCATION
    sent = [r for r in fake_google.writes()[before:] if r.method == "PUT"]
    sent_ids = {r.path.rsplit("/", 1)[1] for r in sent}
    assert isha.id.hex in sent_ids
    assert asr.id.hex not in sent_ids
    # Only masjid prayers changed, so only they were sent again: every later Tuesday's Asr and Isha.
    assert all(r.body.get("location") == KMA_LOCATION for r in sent)
    later = {r.id.hex for r in rows(db, user) if r.kind == "prayer" and r.location and r.starts_at > isha.starts_at.replace(hour=0)}
    assert sent_ids == later
