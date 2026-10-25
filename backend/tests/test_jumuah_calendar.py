"""Friday: Dhuhr becomes Jumuah only when the picker chooses a slot."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tests.calendar_helpers import clock, fetch, google_events, on, refresh, titled
from tests.masjid_helpers import add_masjid, add_user, link, masjid_id, set_jumuah
from tests.mawaqit_pages import conf

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=TORONTO)
FRIDAY = date(2026, 10, 30)
WEEKDAYS = {day: {"dhuhr", "isha"} for day in range(5)}


@pytest.fixture
def user(db, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    return uid


def friday(fake_google) -> list[str]:
    return [e["summary"] for e in on(google_events(fake_google), FRIDAY)]


def test_no_jumuah_masjids_means_a_normal_friday(db, http, user, fake_google):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert "Dhuhr at KMA" in friday(fake_google)
    assert not [s for s in friday(fake_google) if "Jumuah" in s]
    dhuhr = titled(google_events(fake_google), FRIDAY, "Dhuhr at KMA")
    assert "Jumuah" not in dhuhr["description"]


def test_jumuah_replaces_friday_dhuhr(db, http, user, fake_google, ors_key):
    set_jumuah(db, "user-a", ["Kanata Muslim Association"])
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert friday(fake_google) == [
        "Fajr at home", "Drive to KMA", "Jumuah at KMA", "Asr at home", "Maghrib at home", "Drive to KMA", "Isha at KMA",
    ]
    events = google_events(fake_google)
    jumuah = titled(events, FRIDAY, "Jumuah at KMA")
    assert clock(jumuah) == "13:30"
    assert jumuah["description"] == (
        "KMA Jumuah (MAWAQIT, updated Oct 25, 2026)\nEarliest Jumuah that fits, 14 min away."
    )
    drive = on(events, FRIDAY)[1]
    assert (clock(drive), clock(drive, end=True)) == ("13:16", "13:30")
    assert drive["description"].endswith("Arriving at Jumuah time.")
    # Only Friday changes.
    assert "Dhuhr at KMA" in [e["summary"] for e in on(events, date(2026, 10, 29))]


def test_the_shortest_drive_wins(db, http, user, fake_google, fake_mawaqit, fake_ors, ors_key):
    stittsville = add_masjid(db, "Stittsville Masjid", 45.26, -75.92)
    link(db, stittsville, "stittsville", fake_mawaqit, conf(jumua="13:15", jumua2=None))
    set_jumuah(db, "user-a", ["Kanata Muslim Association", "Stittsville Masjid"])
    fake_ors.seconds_to[(45.26, -75.92)] = 6 * 60
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at Stittsville Masjid")
    assert clock(jumuah) == "13:15"
    assert "Shortest drive of your Jumuah masjids (6 min)" in jumuah["description"]


def test_unknown_drive_times_use_the_listed_order(db, http, user, fake_google, fake_mawaqit):
    stittsville = add_masjid(db, "Stittsville Masjid", 45.26, -75.92)
    link(db, stittsville, "stittsville", fake_mawaqit, conf(jumua="13:15", jumua2=None))
    set_jumuah(db, "user-a", ["Stittsville Masjid", "Kanata Muslim Association"])
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    assert clock(titled(events, FRIDAY, "Jumuah at Stittsville Masjid")) == "13:15"
    assert not [e for e in on(events, FRIDAY) if e["summary"].startswith("Drive")]


def test_no_usable_jumuah_times_follows_the_weekly_grid(db, http, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    add_masjid(db, "Jamia Omar")  # not linked to MAWAQIT, so no Jumuah times
    set_jumuah(db, "user-a", ["Jamia Omar"])
    refresh(db, http, uid, NOW)
    dhuhr = titled(google_events(fake_google), FRIDAY, "Dhuhr at KMA")
    assert dhuhr["description"].endswith(
        "Jumuah times aren't available for your Jumuah masjids, so this follows your weekly prayers."
    )
    # The other days don't mention Jumuah.
    thursday = titled(google_events(fake_google), date(2026, 10, 29), "Dhuhr at KMA")
    assert "Jumuah" not in thursday["description"]


def test_a_masjid_with_no_jumuah_on_its_page(db, http, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=WEEKDAYS)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit, conf(jumua=None, jumua2=None))
    set_jumuah(db, "user-a", ["Kanata Muslim Association"])
    fetch(db, http, NOW)
    refresh(db, http, uid, NOW)
    dhuhr = titled(google_events(fake_google), FRIDAY, "Dhuhr at KMA")
    assert clock(dhuhr) == "13:00"  # KMA's Dhuhr iqamah
    assert "Jumuah times aren't available" in dhuhr["description"]


def test_someone_who_prays_at_home_still_gets_jumuah(db, http, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name=None)
    kma = add_masjid(db, "Kanata Muslim Association")
    link(db, kma, "kma-kanata", fake_mawaqit)
    set_jumuah(db, "user-a", ["Kanata Muslim Association"])
    fetch(db, http, NOW)
    refresh(db, http, uid, NOW)
    assert "Jumuah at Kanata Muslim Association" in friday(fake_google)
    # Home prayers stay calculated: there's no main masjid to take adhan times from.
    fajr = titled(google_events(fake_google), FRIDAY, "Fajr at home")
    assert fajr["description"].startswith("Calculated (ISNA, standard Asr)")


def test_jumuah_stays_put_when_nothing_changes(db, http, user, fake_google, ors_key):
    set_jumuah(db, "user-a", ["Kanata Muslim Association"])
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    writes = len(fake_google.writes())
    refresh(db, http, user, NOW)
    assert len(fake_google.writes()) == writes
