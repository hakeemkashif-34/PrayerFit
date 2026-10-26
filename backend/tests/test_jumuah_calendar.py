"""Friday in the calendar: Jumuah on the coming Friday, from MAWAQIT, at the user's pick or the earliest that fits.

The made-up MAWAQIT page has Jumuah at 13:30 (1st) and 14:30 (2nd).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Masjid, UpdateJob, UserSettings
from tests.calendar_helpers import clock, fetch, google_events, on, refresh, source, titled
from tests.masjid_helpers import add_masjid, add_user, link, masjid_id
from tests.mawaqit_pages import conf, page

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=TORONTO)  # Sunday
FRIDAY = date(2026, 10, 30)
NEXT_FRIDAY = date(2026, 11, 6)
WEEKDAYS = {day: {"dhuhr", "isha"} for day in range(5)}


@pytest.fixture
def user(db, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    return uid


def set_settings(db, user, **values):
    with Session(db) as session:
        row = session.scalars(select(UserSettings).where(UserSettings.user_id == user)).one()
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


def set_length(db, name: str, minutes: int | None):
    with Session(db) as session:
        session.scalars(select(Masjid).where(Masjid.name == name)).one().jumuah_minutes = minutes
        session.commit()


def friday(fake_google, day: date = FRIDAY) -> list[str]:
    return [e["summary"] for e in on(google_events(fake_google), day)]


def test_praying_at_home_means_a_normal_friday(db, http, fake_google, fake_mawaqit):
    # Jumuah is always at the main masjid, so someone who prays at home has no Jumuah.
    uid = add_user(fake_google, db, "user-a", masjid_name=None)
    kma = add_masjid(db, "Kanata Muslim Association")
    link(db, kma, "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    refresh(db, http, uid, NOW)
    assert "Dhuhr" in friday(fake_google)
    assert not [s for s in friday(fake_google) if "Jumuah" in s]
    fajr = titled(google_events(fake_google), FRIDAY, "Fajr")
    assert source(db, fajr).startswith("Calculated (ISNA, standard Asr)")


def test_jumuah_replaces_friday_dhuhr_at_the_earliest_slot(db, http, user, fake_google, ors_key):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert friday(fake_google) == [
        "Fajr", "Drive to KMA", "Jumuah at KMA", "Asr", "Maghrib", "Drive to KMA", "Isha at KMA",
    ]
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")
    # No length set for KMA, so 45 minutes.
    assert (clock(jumuah), clock(jumuah, end=True)) == ("13:30", "14:15")
    assert source(db, jumuah) == "KMA Jumuah (MAWAQIT, updated Oct 25, 2026)"
    assert "description" not in jumuah
    # The Jumuah "how early" (5 by default) and the 14 minute drive: leave 1:11.
    drive = on(google_events(fake_google), FRIDAY)[1]
    assert (clock(drive), clock(drive, end=True)) == ("13:11", "13:25")
    assert "description" not in drive


def test_a_set_jumuah_length_is_used(db, http, user, fake_google):
    set_length(db, "Kanata Muslim Association", 40)
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")
    assert clock(jumuah, end=True) == "14:10"


def test_the_jumuah_how_early_is_separate_from_prayers(db, http, user, fake_google, ors_key):
    set_settings(db, user, arrive_early_minutes=0, jumuah_arrive_early_minutes=20)
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    drives = [e for e in on(google_events(fake_google), FRIDAY) if e["summary"] == "Drive to KMA"]
    # Jumuah at 1:30 with 20 minutes early. Isha at 8:15 with 0.
    assert [(clock(e), clock(e, end=True)) for e in drives] == [("12:56", "13:10"), ("20:01", "20:15")]


def test_the_users_pick_is_used(db, http, user, fake_google):
    set_settings(db, user, jumuah_pick_masjid_id=masjid_id(db, "Kanata Muslim Association"), jumuah_pick_order=2)
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at KMA")
    assert clock(jumuah) == "14:30"
    assert "description" not in jumuah


def test_only_the_coming_friday_uses_mawaqits_jumuah_times(db, http, user, fake_google):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert "Jumuah at KMA" in friday(fake_google, FRIDAY)
    # The next Friday follows the weekly grid.
    titled(google_events(fake_google), NEXT_FRIDAY, "Dhuhr at KMA")
    assert not [s for s in friday(fake_google, NEXT_FRIDAY) if "Jumuah" in s]


def test_a_read_after_friday_covers_the_next_one(db, http, user, fake_google, fake_mawaqit):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    with Session(db) as session:
        session.execute(UpdateJob.__table__.delete())
        session.commit()

    # Saturday: KMA has put up the next week's times, an hour earlier after the clocks change.
    saturday = datetime(2026, 10, 31, 8, 0, tzinfo=TORONTO)
    fake_mawaqit.pages["kma-kanata"] = page(conf(jumua="12:30", jumua2="13:30"))
    result = fetch(db, http, saturday)[0]
    assert result.changed
    with Session(db) as session:
        assert session.get(UpdateJob, f"update:{user}").status == "pending"
    refresh(db, http, user, saturday)
    jumuah = titled(google_events(fake_google), NEXT_FRIDAY, "Jumuah at KMA")
    assert clock(jumuah) == "12:30"


def test_no_usable_jumuah_times_follows_the_weekly_grid(db, http, fake_google):
    # KMA isn't linked to MAWAQIT, so it has no Jumuah times.
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    refresh(db, http, uid, NOW)
    dhuhr = titled(google_events(fake_google), FRIDAY, "Dhuhr at KMA")
    assert "description" not in dhuhr


def test_a_masjid_with_no_jumuah_on_its_page(db, http, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit, conf(jumua=None, jumua2=None))
    fetch(db, http, NOW)
    refresh(db, http, uid, NOW)
    dhuhr = titled(google_events(fake_google), FRIDAY, "Dhuhr at KMA")
    assert clock(dhuhr) == "13:00"  # KMA's Dhuhr iqamah


def test_jumuah_stays_put_when_nothing_changes(db, http, user, fake_google, ors_key):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    writes = len(fake_google.writes())
    refresh(db, http, user, NOW + timedelta(minutes=5))
    assert len(fake_google.writes()) == writes


def test_each_prayer_block_has_its_length_and_jumuah_uses_the_masjids(db, http, user, fake_google):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)

    def minutes(event: dict) -> int:
        start = datetime.fromisoformat(event["start"]["dateTime"])
        return int((datetime.fromisoformat(event["end"]["dateTime"]) - start).total_seconds() // 60)

    prayers = [e for e in google_events(fake_google) if not e["summary"].startswith("Drive")]
    assert {minutes(e) for e in prayers if e["summary"].startswith("Jumuah")} == {45}
    by_prayer = {
        name: {minutes(e) for e in prayers if e["summary"].startswith(name)}
        for name in ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
    }
    assert by_prayer == {"Fajr": {10}, "Dhuhr": {15}, "Asr": {10}, "Maghrib": {10}, "Isha": {15}}
    # Only the coming Friday has Jumuah.
    assert len([e for e in prayers if e["summary"].startswith("Jumuah")]) == 1
