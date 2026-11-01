"""Announced masjid times: a masjid's own announcement wins over MAWAQIT on its dates.

The made-up MAWAQIT page has the same times every day: Fajr adhan 5:30 with
iqamah "+20" (5:50), Dhuhr 13:00, Asr "+10" (15:40), Maghrib adhan 18:00
with "+5" (18:05), Isha 20:15, and Jumuah at 13:30 and 14:30.

The test announcement is KMA's real one (announced/kma.json) with the test
masjid's MAWAQIT ID, so the tests check the real times too.
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.masjid_times import announced
from app.masjid_times.announced import BadAnnouncement, Rule, announcement_for, parse
from app.prayer_times import calculate_prayer_times
from tests.calendar_helpers import clock, fetch, google_events, on, refresh, source, titled
from tests.masjid_helpers import add_user, link, masjid_id

TORONTO = ZoneInfo("America/Toronto")
REAL_FILE = Path(announced.__file__).parent / "announced" / "kma.json"
EVERY_PRAYER = {day: {"fajr", "dhuhr", "asr", "maghrib", "isha"} for day in range(7)}
# Thursday. The window runs Oct 29 to Nov 11, across the Nov 1 clock change.
NOW = datetime(2026, 10, 29, 8, 0, tzinfo=TORONTO)


def kma_file(mawaqit_id: str = "kma-kanata") -> dict:
    data = json.loads(REAL_FILE.read_text())
    data["mawaqit_ids"] = [mawaqit_id]
    return data


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A folder of announcement files for one test. Clears the loader's cache."""
    monkeypatch.setattr(announced, "ANNOUNCED_DIR", tmp_path)
    announced._load_dir.cache_clear()
    yield tmp_path
    announced._load_dir.cache_clear()


def write(folder: Path, name: str, data) -> None:
    (folder / name).write_text(data if isinstance(data, str) else json.dumps(data))


# ---- The file ----


@pytest.mark.real_announcements
def test_the_real_kma_file_loads():
    announced._load_dir.cache_clear()
    kma = announcement_for("id/9793")
    assert kma is not None and kma.label == "KMA announcement"
    assert announcement_for("kma-masjid-ottawa") is kma
    day = kma.day(date(2026, 11, 6))
    assert day.iqamah == {
        "fajr": Rule(base="adhan", minutes=15),
        "dhuhr": Rule(clock=datetime(2026, 1, 1, 12, 30).time()),
        "asr": Rule(clock=datetime(2026, 1, 1, 15, 15).time()),
        "maghrib": Rule(base="sunset", minutes=5),
        "isha": Rule(clock=datetime(2026, 1, 1, 19, 40).time()),
    }
    jumuah = {d: [j.time.strftime("%H:%M") for j in kma.day(date(2026, 11, d)).jumuah] for d in (6, 13, 20, 27)}
    assert jumuah == {
        6: ["11:30", "12:40", "13:40"],
        13: ["11:30", "12:40", "13:35"],
        20: ["11:30", "12:40", "13:30"],
        27: ["11:30", "12:40", "13:30"],
    }
    assert kma.day(date(2026, 10, 31)) is None
    assert kma.day(date(2026, 12, 1)) is None
    # Only Fridays get Jumuah.
    assert kma.day(date(2026, 11, 7)).jumuah == ()
    announced._load_dir.cache_clear()


def test_offsets_and_clock_times_are_read():
    data = {"label": "X", "mawaqit_ids": ["x"], "entries": [
        {"start": "2026-11-01", "end": "2026-11-01", "iqamah": {"fajr": "adhan+15", "maghrib": "sunset + 5", "isha": "7:40"}},
    ]}
    day = parse(data, "x").day(date(2026, 11, 1))
    assert day.iqamah["fajr"] == Rule(base="adhan", minutes=15)
    assert day.iqamah["maghrib"].text() == "5 minutes after sunset"
    assert day.iqamah["isha"].text() == "07:40"


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"start": "2026-11-01", "end": "2026-10-31", "iqamah": {"isha": "19:40"}}, "ends before it starts"),
        ({"start": "2026-11-01", "end": "2026-11-30", "iqamah": {"isha": "7:40 pm"}}, "isha must be a clock time"),
        ({"start": "2026-11-01", "end": "2026-11-30", "iqamah": {"isha": "25:00"}}, "isha must be a clock time"),
        ({"start": "2026-11-01", "end": "2026-11-30", "iqamah": {"fajr": "adhan + 200"}}, "more than 120 minutes"),
        ({"start": "2026-11-01", "end": "2026-11-30", "iqamah": {"jumuah": "12:00"}}, "unknown prayers"),
        ({"start": "Nov 1", "end": "2026-11-30", "iqamah": {"isha": "19:40"}}, "start must be a date"),
        ({"start": "2026-11-06", "end": "2026-11-06", "jumuah": ["12:40", "11:30"]}, "in order"),
        ({"start": "2026-11-06", "end": "2026-11-06", "jumuah": ["11", "12", "13", "14"]}, "up to 3"),
        ({"start": "2026-11-07", "end": "2026-11-08", "jumuah": ["11:30"]}, "has no Friday"),
        ({"start": "2026-11-01", "end": "2026-11-30"}, "no iqamah or jumuah"),
        ({"start": "2026-11-01", "end": "2026-11-30", "isha": "19:40"}, "unknown keys"),
    ],
)
def test_a_bad_entry_is_refused(entry, message):
    with pytest.raises(BadAnnouncement, match=message):
        parse({"label": "X", "mawaqit_ids": ["x"], "entries": [entry]}, "x")


def test_2_entries_giving_the_same_prayer_on_the_same_date_are_refused():
    data = {"label": "X", "mawaqit_ids": ["x"], "entries": [
        {"start": "2026-11-01", "end": "2026-11-30", "iqamah": {"isha": "19:40"}},
        {"start": "2026-11-30", "end": "2026-12-31", "iqamah": {"isha": "19:30"}},
    ]}
    with pytest.raises(BadAnnouncement, match="entries 1 and 2 both give isha"):
        parse(data, "x")


def test_a_missing_folder_means_no_announcements(folder):
    announced.ANNOUNCED_DIR = folder / "not-there"
    assert announcement_for("kma-kanata") is None


def test_a_broken_file_is_logged_and_skipped_and_other_files_still_load(folder, caplog):
    write(folder, "broken.json", "{not json")
    write(folder, "bad.json", {"label": "Bad", "mawaqit_ids": ["bad"], "entries": [{"start": "x"}]})
    write(folder, "kma.json", kma_file())
    with caplog.at_level(logging.ERROR, logger="app.masjid_times.announced"):
        assert announcement_for("bad") is None
        assert announcement_for("kma-kanata") is not None
    assert "broken.json weren't used" in caplog.text
    assert "bad.json weren't used" in caplog.text


def test_the_same_mawaqit_id_in_2_files_uses_only_the_first(folder, caplog):
    write(folder, "a.json", kma_file())
    write(folder, "b.json", {**kma_file(), "label": "Other"})
    with caplog.at_level(logging.ERROR, logger="app.masjid_times.announced"):
        assert announcement_for("kma-kanata").label == "KMA announcement"
    assert "b.json weren't used: kma-kanata is already in another file" in caplog.text


# ---- In the calendar ----


@pytest.fixture
def user(db, fake_google, fake_mawaqit):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA", at_masjid=EVERY_PRAYER)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    return uid


def iqamah(fake_google, day: date) -> dict[str, str]:
    events = google_events(fake_google)
    names = {"Fajr": "fajr", "Dhuhr": "dhuhr", "Asr": "asr", "Maghrib": "maghrib", "Isha": "isha"}
    return {names[e["summary"].split(" at ")[0]]: clock(e) for e in on(events, day) if e["summary"].split(" at ")[0] in names}


def test_a_date_inside_the_range_uses_the_announced_times(db, http, user, fake_google, folder):
    write(folder, "kma.json", kma_file())
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    # Monday, Nov 2. Fajr is MAWAQIT's 5:30 adhan + 15, Maghrib its 18:00 sunset + 5.
    assert iqamah(fake_google, date(2026, 11, 2)) == {
        "fajr": "05:45", "dhuhr": "12:30", "asr": "15:15", "maghrib": "18:05", "isha": "19:40",
    }
    events = google_events(fake_google)
    day = date(2026, 11, 2)
    assert source(db, titled(events, day, "Isha at KMA")) == "KMA iqamah (KMA announcement)"
    assert source(db, titled(events, day, "Fajr at KMA")) == (
        "KMA iqamah (KMA announcement: 15 minutes after KMA's adhan time from MAWAQIT)"
    )
    assert source(db, titled(events, day, "Maghrib at KMA")) == (
        "KMA iqamah (KMA announcement: 5 minutes after KMA's sunset time from MAWAQIT)"
    )
    # Events still have no description.
    assert "description" not in titled(events, day, "Isha at KMA")


def test_a_date_outside_the_range_uses_mawaqit(db, http, user, fake_google, folder):
    write(folder, "kma.json", kma_file())
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    # Saturday, Oct 31, the day before the range starts.
    assert iqamah(fake_google, date(2026, 10, 31)) == {
        "fajr": "05:50", "dhuhr": "13:00", "asr": "15:40", "maghrib": "18:05", "isha": "20:15",
    }
    isha = titled(google_events(fake_google), date(2026, 10, 31), "Isha at KMA")
    assert source(db, isha) == "KMA iqamah (MAWAQIT, updated Oct 29, 2026)"


def test_home_prayers_keep_the_adhan_time(db, http, fake_google, fake_mawaqit, folder):
    write(folder, "kma.json", kma_file())
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA")
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, NOW)
    refresh(db, http, uid, NOW)
    isha = titled(google_events(fake_google), date(2026, 11, 2), "Isha")
    assert clock(isha) == "19:30"
    assert source(db, isha) == "KMA adhan time (MAWAQIT)"


def test_offsets_across_the_clock_change_use_mawaqits_adhan(db, http, user, fake_google, folder):
    # Nov 1 is the first day of the range and the day the clocks go back.
    write(folder, "kma.json", kma_file())
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    for day in (date(2026, 11, 1), date(2026, 11, 2)):
        fajr = titled(google_events(fake_google), day, "Fajr at KMA")
        assert fajr["start"]["dateTime"] == f"{day}T05:45:00-05:00"
        maghrib = titled(google_events(fake_google), day, "Maghrib at KMA")
        assert maghrib["start"]["dateTime"] == f"{day}T18:05:00-05:00"


def test_offsets_use_the_calculated_adhan_when_mawaqit_isnt_usable(db, http, user, fake_google, folder):
    # Linked, but never read, so there are no MAWAQIT times. The announcement still applies.
    write(folder, "kma.json", kma_file())
    refresh(db, http, user, NOW)
    from app.user_settings import load_setup
    from sqlalchemy.orm import Session

    with Session(db) as session:
        setup = load_setup(session, user)
    for day in (date(2026, 11, 1), date(2026, 11, 2)):
        calculated = calculate_prayer_times(setup.latitude, setup.longitude, day, setup.time_zone, setup.method, setup.asr_method)
        events = google_events(fake_google)
        fajr = titled(events, day, "Fajr at KMA")
        expected = (calculated.fajr.time + timedelta(minutes=15)).astimezone(TORONTO)
        assert datetime.fromisoformat(fajr["start"]["dateTime"]) == expected
        assert fajr["start"]["dateTime"].endswith("-05:00")
        assert source(db, fajr) == (
            "KMA iqamah (KMA announcement: 15 minutes after the calculated adhan time (ISNA, standard Asr))"
        )
        maghrib = titled(events, day, "Maghrib at KMA")
        assert datetime.fromisoformat(maghrib["start"]["dateTime"]) == calculated.maghrib.time + timedelta(minutes=5)
        assert source(db, maghrib).endswith("5 minutes after the calculated sunset time (ISNA, standard Asr))")
        # Clock times don't need MAWAQIT at all.
        assert clock(titled(events, day, "Isha at KMA")) == "19:40"


def test_drive_blocks_use_the_announced_time(db, http, user, fake_google, folder, ors_key):
    write(folder, "kma.json", kma_file())
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    day = on(google_events(fake_google), date(2026, 11, 2))
    isha = next(n for n, e in enumerate(day) if e["summary"] == "Isha at KMA")
    drive = day[isha - 1]
    assert drive["summary"] == "Drive to KMA"
    # Prayers arrive 0 minutes early by default, so the drive ends at 7:40.
    assert clock(drive, end=True) == "19:40"


def test_a_busy_announced_iqamah_moves_home(db, http, user, fake_google, folder):
    write(folder, "kma.json", kma_file())
    # Busy 7:00 to 7:50 pm on Nov 2 covers the 7:40 announced Isha.
    fake_google.busy["user-a"] = [("2026-11-03T00:00:00Z", "2026-11-03T00:50:00Z")]
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    isha = titled(events, date(2026, 11, 2), "Isha")
    # At home, after the busy time, not at 7:40.
    assert clock(isha) == "19:50"
    assert source(db, isha) == "KMA iqamah (KMA announcement)"


def test_a_broken_file_falls_back_to_mawaqit_in_the_calendar(db, http, user, fake_google, folder, caplog):
    write(folder, "kma.json", "{\"label\": ")
    fetch(db, http, NOW)
    with caplog.at_level(logging.ERROR, logger="app.masjid_times.announced"):
        refresh(db, http, user, NOW)
    assert iqamah(fake_google, date(2026, 11, 2))["isha"] == "20:15"
    assert "kma.json weren't used" in caplog.text


def test_no_file_falls_back_to_mawaqit_in_the_calendar(db, http, user, fake_google, folder):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert iqamah(fake_google, date(2026, 11, 2))["isha"] == "20:15"


# ---- Jumuah ----


def jumuah_on(db, fake_google, day: date) -> tuple[str, str]:
    jumuah = titled(google_events(fake_google), day, "Jumuah at KMA")
    return clock(jumuah), source(db, jumuah)


@pytest.mark.parametrize(
    "friday, third",
    [(date(2026, 11, 6), "13:40"), (date(2026, 11, 13), "13:35"), (date(2026, 11, 20), "13:30"), (date(2026, 11, 27), "13:30")],
)
def test_the_jumuah_chooser_picks_from_the_announced_times(db, http, user, fake_google, folder, friday, third):
    from tests.test_jumuah_calendar import set_settings

    write(folder, "kma.json", kma_file())
    set_settings(db, user, jumuah_pick_masjid_id=masjid_id(db, "Kanata Muslim Association"), jumuah_pick_order=3)
    now = datetime.combine(friday - timedelta(days=1), datetime.min.time(), TORONTO).replace(hour=8)
    fetch(db, http, now)
    refresh(db, http, user, now)
    assert jumuah_on(db, fake_google, friday) == (third, "KMA Jumuah (KMA announcement)")


def test_a_busy_pick_uses_the_earliest_announced_jumuah_that_fits(db, http, user, fake_google, folder):
    from tests.test_jumuah_calendar import set_settings

    write(folder, "kma.json", kma_file())
    set_settings(db, user, jumuah_pick_masjid_id=masjid_id(db, "Kanata Muslim Association"), jumuah_pick_order=1)
    # Busy 11:00 am to 12:00 pm on Nov 6 covers the 11:30 Jumuah.
    fake_google.busy["user-a"] = [("2026-11-06T16:00:00Z", "2026-11-06T17:00:00Z")]
    now = datetime(2026, 11, 5, 8, 0, tzinfo=TORONTO)
    fetch(db, http, now)
    refresh(db, http, user, now)
    jumuah = titled(google_events(fake_google), date(2026, 11, 6), "Jumuah at KMA")
    assert clock(jumuah) == "12:40"
    assert jumuah["description"].startswith("Your pick (1st Jumuah) clashes with your calendar")


def test_a_later_friday_with_announced_jumuah_gets_jumuah(db, http, user, fake_google, folder):
    # MAWAQIT only has the coming Friday's Jumuah. An announcement covers later ones too.
    write(folder, "kma.json", kma_file())
    now = datetime(2026, 11, 5, 8, 0, tzinfo=TORONTO)
    fetch(db, http, now)
    refresh(db, http, user, now)
    assert jumuah_on(db, fake_google, date(2026, 11, 6))[0] == "11:30"
    assert jumuah_on(db, fake_google, date(2026, 11, 13))[0] == "11:30"


def test_a_friday_outside_the_range_uses_mawaqits_jumuah(db, http, user, fake_google, folder):
    write(folder, "kma.json", kma_file())
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    assert jumuah_on(db, fake_google, date(2026, 10, 30)) == ("13:30", "KMA Jumuah (MAWAQIT, updated Oct 29, 2026)")


# ---- Settings ----


def test_settings_says_when_announced_times_are_used(client, fake_google, fake_photon, fake_mawaqit, db, http, set_today, folder):
    from tests.conftest import sign_in
    from tests.setup_helpers import setup_through_api

    write(folder, "kma.json", kma_file())
    sign_in(client, fake_google)
    set_today(date(2026, 11, 2))
    assert setup_through_api(client, fake_photon).status_code == 200
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    fetch(db, http, datetime(2026, 11, 2, 8, 0, tzinfo=TORONTO))
    status = client.get("/settings").json()["main_masjid"]["iqamah_status"]
    assert status.endswith(". Iqamah and Jumuah times from the KMA announcement are used from Nov 1 to Nov 30, 2026")
