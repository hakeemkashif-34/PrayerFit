"""The 14-day window across Toronto's daylight saving changes in 2026.

November 1: clocks fall back from 2:00 to 1:00 (-04:00 to -05:00). That day has 25 hours.
March 8: clocks jump from 2:00 to 3:00 (-05:00 to -04:00). That day has 23 hours.
If the window moved by adding 24 hours, it would skip or repeat a day here.
"""

from datetime import date, datetime, timedelta

import pytest

from app.calendar_window import window_dates
from app.prayer_times import calculate_prayer_times
from tests.conftest import sign_in
from tests.setup_helpers import save_setup

TORONTO = (43.6532, -79.3832)
PRAYERS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]


@pytest.mark.parametrize(
    "first_day, change_day, before, after",
    [
        (date(2026, 10, 25), date(2026, 11, 1), "-04:00", "-05:00"),  # fall back
        (date(2026, 11, 1), date(2026, 11, 1), "-04:00", "-05:00"),  # starting on the change day
        (date(2026, 3, 1), date(2026, 3, 8), "-05:00", "-04:00"),  # spring forward
    ],
)
def test_window_across_daylight_saving(client, fake_google, set_today, db, first_day, change_day, before, after):
    sign_in(client, fake_google)
    save_setup(db, location=TORONTO)
    set_today(first_day)

    assert client.post("/calendar/sync").json()["sent"] == 70

    events = fake_google.live_events(fake_google.calendars_of("user-a")[0].id)
    by_day: dict[date, list[dict]] = {}
    for event in events:
        start = datetime.fromisoformat(event["start"]["dateTime"])
        by_day.setdefault(start.date(), []).append(event)

    # 14 calendar days in a row, none skipped or repeated, 5 prayers each.
    assert sorted(by_day) == [first_day + timedelta(days=n) for n in range(14)]
    assert all(len(day_events) == 5 for day_events in by_day.values())

    for day, day_events in by_day.items():
        expected = calculate_prayer_times(*TORONTO, day, "America/Toronto")
        offset = after if day >= change_day else before
        day_events.sort(key=lambda e: e["start"]["dateTime"])
        for event, name in zip(day_events, PRAYERS):
            start = datetime.fromisoformat(event["start"]["dateTime"])
            end = datetime.fromisoformat(event["end"]["dateTime"])
            assert start == getattr(expected, name).time
            assert event["start"]["dateTime"].endswith(offset)
            # 15 real minutes, even on the change day.
            assert end - start == timedelta(minutes=15)


def test_window_dates_never_add_24_hours():
    # November 1 has 25 hours, but the window still steps one calendar day at a time.
    assert window_dates(date(2026, 10, 31), 3) == [date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)]
    assert len(window_dates(date(2026, 10, 25))) == 14
