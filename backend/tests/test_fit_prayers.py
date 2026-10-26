"""The pure fitting rules: free gaps, shrinking, prayer windows, and daylight saving."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.fit_prayers import (
    PrayerWindow,
    earliest_gap,
    fit_prayer,
    masjid_is_free,
    midnight,
    prayer_windows,
)
from app.prayer_times import calculate_prayer_times

TORONTO = ZoneInfo("America/Toronto")
TEN, FIFTEEN = timedelta(minutes=10), timedelta(minutes=15)


def at(hour: int, minute: int = 0, day: int = 26, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TORONTO)


# Isha from 7:23 pm to 12:41 am.
ISHA = PrayerWindow(at(19, 23), at(0, 41, day=27))
# Asr from 3:36 pm to Maghrib at 6:01 pm.
ASR = PrayerWindow(at(15, 36), at(18, 1))


def test_a_free_normal_time_stays():
    fit = fit_prayer(ISHA, at(19, 23), FIFTEEN, [(at(17, 0), at(19, 0))])
    assert (fit.kind, fit.starts_at, fit.length) == ("normal", at(19, 23), FIFTEEN)


def test_an_event_ending_exactly_at_the_normal_time_doesnt_clash():
    assert fit_prayer(ISHA, at(19, 40), FIFTEEN, [(at(19, 0), at(19, 40))]).kind == "normal"
    assert fit_prayer(ISHA, at(19, 40), FIFTEEN, [(at(19, 55), at(21, 0))]).kind == "normal"


def test_praying_before_an_event():
    # Isha starts at 7:23, a meeting runs 7:45 to 9:00. The normal time (7:40) clashes.
    fit = fit_prayer(ISHA, at(19, 40), FIFTEEN, [(at(19, 45), at(21, 0))])
    assert (fit.kind, fit.starts_at, fit.length) == ("moved", at(19, 23), FIFTEEN)


def test_praying_after_an_event():
    # Class 4:00 to 5:00 covers Asr's normal time. Asr goes at 5:00.
    fit = fit_prayer(PrayerWindow(at(15, 50), at(18, 1)), at(15, 50), TEN, [(at(15, 45), at(17, 0))])
    assert (fit.kind, fit.starts_at) == ("moved", at(17, 0))


def test_gaps_under_10_minutes_are_skipped():
    # A 9-minute gap at 7:23, then busy until 8:00.
    busy = [(at(19, 32), at(20, 0))]
    fit = fit_prayer(ISHA, at(19, 40), FIFTEEN, busy)
    assert (fit.kind, fit.starts_at) == ("moved", at(20, 0))


def test_a_prayer_shrinks_to_fit_a_shorter_gap():
    # 12 minutes free at 7:23 fits Isha as a 12-minute block.
    fit = fit_prayer(ISHA, at(19, 40), FIFTEEN, [(at(19, 35), at(23, 59))])
    assert (fit.kind, fit.starts_at, fit.length) == ("moved", at(19, 23), timedelta(minutes=12))
    assert fit.ends_at == at(19, 35)


def test_exactly_10_minutes_is_enough():
    assert earliest_gap(ASR, TEN, [(at(15, 46), at(18, 30))]) == (at(15, 36), TEN)


def test_a_moved_prayer_fits_fully_before_its_time_ends():
    # Busy until 5:55 pm: only 6 minutes are left before Maghrib at 6:01.
    fit = fit_prayer(ASR, at(16, 15), TEN, [(at(15, 0), at(17, 55))])
    assert (fit.kind, fit.starts_at) == ("clash", at(16, 15))
    # Busy until 5:51: exactly 10 minutes left.
    fit = fit_prayer(ASR, at(16, 15), TEN, [(at(15, 0), at(17, 51))])
    assert (fit.kind, fit.starts_at, fit.ends_at) == ("moved", at(17, 51), at(18, 1))


def test_no_free_time_at_all_is_a_clash_at_the_normal_time():
    fit = fit_prayer(ASR, at(16, 15), TEN, [(at(15, 0), at(18, 30))])
    assert (fit.kind, fit.starts_at, fit.length) == ("clash", at(16, 15), TEN)


def test_overlapping_events_are_joined():
    busy = [(at(15, 0), at(16, 0)), (at(15, 50), at(16, 30)), (at(16, 30), at(16, 35))]
    assert earliest_gap(ASR, TEN, busy) == (at(16, 35), TEN)


def test_a_moved_prayer_avoids_the_apps_own_events():
    # Busy over the normal time. Maghrib's drive block at 5:40 is taken too.
    window = PrayerWindow(at(17, 0), at(18, 1))
    fit = fit_prayer(window, at(17, 0), TEN, [(at(16, 0), at(17, 35))], taken=[(at(17, 40), at(18, 1))])
    assert fit.kind == "clash"


def test_the_apps_own_events_dont_move_a_free_normal_time():
    fit = fit_prayer(ASR, at(16, 15), TEN, [], taken=[(at(16, 10), at(16, 20))])
    assert fit.kind == "normal"


def test_a_moved_prayer_never_starts_in_the_past():
    # It's 7:31:20 pm. The gap at 7:23 has already begun, so the earliest is 7:32.
    fit = fit_prayer(ISHA, at(19, 40), FIFTEEN, [(at(19, 45), at(21, 0))], not_before=at(19, 31) + timedelta(seconds=20))
    assert (fit.kind, fit.starts_at, fit.length) == ("moved", at(19, 32), timedelta(minutes=13))


def test_fajr_ends_at_sunrise():
    day = calculate_prayer_times(45.4215, -75.6972, date(2026, 10, 26), "America/Toronto")
    tomorrow = calculate_prayer_times(45.4215, -75.6972, date(2026, 10, 27), "America/Toronto")
    starts = {name: getattr(day, name).time for name in ("fajr", "dhuhr", "asr", "maghrib", "isha")}
    windows = prayer_windows(starts, day.sunrise.time, tomorrow.fajr.time)
    assert windows["fajr"] == PrayerWindow(day.fajr.time, day.sunrise.time)
    # Busy from Fajr until 9 minutes before sunrise: no room for Fajr.
    busy = [(day.fajr.time - timedelta(minutes=5), day.sunrise.time - timedelta(minutes=9))]
    assert fit_prayer(windows["fajr"], day.fajr.time, TEN, busy).kind == "clash"
    busy = [(day.fajr.time - timedelta(minutes=5), day.sunrise.time - timedelta(minutes=10))]
    assert fit_prayer(windows["fajr"], day.fajr.time, TEN, busy).ends_at == day.sunrise.time


def test_the_other_windows_end_at_the_next_prayer():
    starts = {"fajr": at(6, 0), "dhuhr": at(12, 48), "asr": at(15, 36), "maghrib": at(18, 1), "isha": at(19, 23)}
    windows = prayer_windows(starts, at(7, 31), at(6, 1, day=27))
    assert windows["dhuhr"].ends_at == at(15, 36)
    assert windows["asr"].ends_at == at(18, 1)
    assert windows["maghrib"].ends_at == at(19, 23)


def test_isha_ends_at_midnight_halfway_between_maghrib_and_fajr():
    # Maghrib 6:01 pm, next Fajr 6:01 am: midnight is 12:01 am, not 2 am.
    assert midnight(at(18, 1), at(6, 1, day=27)) == at(0, 1, day=27)
    # Rounded down: 6:01 pm to 6:02 am is 12 h 1 min, so halfway is 12:01:30, shown as 12:01.
    assert midnight(at(18, 1), at(6, 2, day=27)) == at(0, 1, day=27)
    # Busy all evening until 12:00 am: Isha has 1 minute left, so it's a clash.
    window = PrayerWindow(at(19, 23), midnight(at(18, 1), at(6, 1, day=27)))
    assert fit_prayer(window, at(19, 23), FIFTEEN, [(at(19, 0), at(0, 0, day=27))]).kind == "clash"
    # Busy until 11:46 pm: a 15-minute Isha fits right before midnight.
    fit = fit_prayer(window, at(19, 23), FIFTEEN, [(at(19, 0), at(23, 46))])
    assert (fit.starts_at, fit.ends_at) == (at(23, 46), at(0, 1, day=27))


def test_midnight_on_the_night_the_clocks_go_back():
    # Oct 31 to Nov 1, 2026: 1:00 to 2:00 am happens twice in Toronto.
    day = calculate_prayer_times(45.4215, -75.6972, date(2026, 10, 31), "America/Toronto")
    tomorrow = calculate_prayer_times(45.4215, -75.6972, date(2026, 11, 1), "America/Toronto")
    middle = midnight(day.maghrib.time, tomorrow.fajr.time)
    real = (tomorrow.fajr.time.astimezone(ZoneInfo("UTC")) - day.maghrib.time.astimezone(ZoneInfo("UTC"))) / 2
    gap = middle.astimezone(ZoneInfo("UTC")) - day.maghrib.time.astimezone(ZoneInfo("UTC"))
    # The real halfway point, counted in real hours, not wall clock hours.
    assert timedelta(0) <= real - gap < timedelta(minutes=1)
    assert middle.utcoffset() == timedelta(hours=-4)  # 12:xx am on Nov 1 is still daylight time


def test_moving_on_the_day_the_clocks_go_back():
    # Nov 1, 2026 has 1:00 to 1:59 am twice. Busy from 1:00 am (EDT) to 1:30 am (EST),
    # which is 1.5 real hours. A window from 12:50 am EDT to 3:00 am EST.
    second_one_thirty = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=TORONTO)
    window = PrayerWindow(datetime(2026, 11, 1, 0, 50, tzinfo=TORONTO), datetime(2026, 11, 1, 3, 0, tzinfo=TORONTO))
    fit = fit_prayer(window, window.starts_at, FIFTEEN, [(datetime(2026, 11, 1, 0, 55, tzinfo=TORONTO), second_one_thirty)])
    assert fit.kind == "moved"
    assert fit.starts_at.astimezone(ZoneInfo("UTC")) == second_one_thirty.astimezone(ZoneInfo("UTC"))
    assert fit.starts_at.utcoffset() == timedelta(hours=-5)


def test_moving_on_the_day_the_clocks_go_forward():
    # Mar 8, 2026: 2:00 am jumps to 3:00 am. Busy 1:50 am to 3:10 am is 20 real minutes.
    window = PrayerWindow(datetime(2026, 3, 8, 1, 45, tzinfo=TORONTO), datetime(2026, 3, 8, 4, 0, tzinfo=TORONTO))
    busy = [(datetime(2026, 3, 8, 1, 50, tzinfo=TORONTO), datetime(2026, 3, 8, 3, 10, tzinfo=TORONTO))]
    fit = fit_prayer(window, window.starts_at, FIFTEEN, busy)
    assert (fit.kind, fit.starts_at) == ("moved", datetime(2026, 3, 8, 3, 10, tzinfo=TORONTO))
    assert fit.ends_at == datetime(2026, 3, 8, 3, 25, tzinfo=TORONTO)


def test_the_masjid_needs_the_drive_how_early_and_the_prayer_all_free():
    # Isha iqamah 7:40, 5 minutes early, 10 minute drive: from 7:25 to 7:55.
    assert masjid_is_free(at(19, 40), 5, 600, FIFTEEN, [(at(19, 0), at(19, 25))])
    assert not masjid_is_free(at(19, 40), 5, 600, FIFTEEN, [(at(19, 0), at(19, 26))])
    assert not masjid_is_free(at(19, 40), 5, 600, FIFTEEN, [(at(19, 54), at(20, 0))])
    assert masjid_is_free(at(19, 40), 5, 600, FIFTEEN, [(at(19, 55), at(20, 0))])
    # No drive time: from arriving at 7:35.
    assert masjid_is_free(at(19, 40), 5, None, FIFTEEN, [(at(19, 0), at(19, 35))])
