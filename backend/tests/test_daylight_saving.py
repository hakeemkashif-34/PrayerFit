"""Prayer times on the days Toronto changes its clocks.

Clocks jump forward an hour on March 8, 2026 and back an hour on November 1, 2026.
The sun doesn't care, so the real time between one Dhuhr and the next is still
about 24 hours. Only the clock on the wall moves by an hour.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.prayer_times import calculate_prayer_times
from tests.places import TORONTO

SPRING_FORWARD = date(2026, 3, 8)  # 2:00 am becomes 3:00 am
FALL_BACK = date(2026, 11, 1)  # 2:00 am becomes 1:00 am
EST = timedelta(hours=-5)  # winter
EDT = timedelta(hours=-4)  # summer

CHANGES = [
    pytest.param(SPRING_FORWARD, EST, EDT, 60, id="spring"),
    pytest.param(FALL_BACK, EDT, EST, -60, id="fall"),
]


def toronto(day):
    return calculate_prayer_times(TORONTO.latitude, TORONTO.longitude, day, TORONTO.timezone)


def minutes_after_midnight(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def test_change_days_are_right():
    """Check the test's own dates against the time zone rules."""
    zone = ZoneInfo("America/Toronto")
    for day, before, after in [(SPRING_FORWARD, EST, EDT), (FALL_BACK, EDT, EST)]:
        assert datetime(day.year, day.month, day.day, 0, 30, tzinfo=zone).utcoffset() == before
        assert datetime(day.year, day.month, day.day, 12, tzinfo=zone).utcoffset() == after


@pytest.mark.parametrize("change_day, offset_before, offset_after, clock_jump", CHANGES)
def test_whole_week_has_right_offset_and_date(change_day, offset_before, offset_after, clock_jump):
    for days in range(-3, 4):
        day = change_day + timedelta(days=days)
        expected_offset = offset_before if day < change_day else offset_after
        for name, prayer in toronto(day).in_order():
            # Every time is on the date that was asked for, never the day before or after.
            assert prayer.time.date() == day, f"{day} {name}"
            assert prayer.time.utcoffset() == expected_offset, f"{day} {name}"


@pytest.mark.parametrize("change_day, offset_before, offset_after, clock_jump", CHANGES)
def test_clock_jumps_but_real_time_does_not(change_day, offset_before, offset_after, clock_jump):
    before = toronto(change_day - timedelta(days=1))
    after = toronto(change_day)

    for (name, earlier), (_, later) in zip(before.in_order(), after.in_order()):
        # On the wall clock, every prayer moves by about an hour.
        wall_clock_change = minutes_after_midnight(later.time) - minutes_after_midnight(earlier.time)
        assert abs(wall_clock_change - clock_jump) <= 3, name

        # In real time, it's about a day later. Convert to UTC first: subtracting
        # two Toronto times in Python compares wall clocks, which would give 23 or 25 hours.
        real_gap = later.time.astimezone(timezone.utc) - earlier.time.astimezone(timezone.utc)
        assert abs(real_gap - timedelta(days=1)) <= timedelta(minutes=3), name
