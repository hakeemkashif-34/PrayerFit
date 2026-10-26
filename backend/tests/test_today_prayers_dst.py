"""Event times on Toronto's daylight saving days in 2026.

March 8: clocks jump from 2:00 to 3:00 (EST -05:00 to EDT -04:00).
November 1: clocks fall back from 2:00 to 1:00 (EDT -04:00 to EST -05:00).
All 5 prayers are after 2 am, so every event that day uses the new offset.
"""

from datetime import date, datetime, timedelta

import pytest

from app.prayer_times import calculate_prayer_times
from tests.conftest import sign_in
from tests.setup_helpers import save_setup

# Fajr, Asr, and Maghrib blocks are 10 minutes. Dhuhr and Isha are 15.
MINUTES = {"fajr": 10, "dhuhr": 15, "asr": 10, "maghrib": 10, "isha": 15}
TORONTO = {"latitude": 43.6532, "longitude": -79.3832, "timezone": "America/Toronto"}


@pytest.mark.parametrize(
    "day, offset",
    [
        (date(2026, 3, 7), "-05:00"),  # the day before spring forward
        (date(2026, 3, 8), "-04:00"),  # spring forward
        (date(2026, 10, 31), "-04:00"),  # the day before fall back
        (date(2026, 11, 1), "-05:00"),  # fall back
    ],
)
def test_event_times_on_daylight_saving_days(client, fake_google, set_today, db, day, offset):
    sign_in(client, fake_google)
    save_setup(db, location=(TORONTO["latitude"], TORONTO["longitude"]))
    set_today(day)

    response = client.post("/prayers/today")

    assert response.status_code == 200
    expected = calculate_prayer_times(TORONTO["latitude"], TORONTO["longitude"], day, TORONTO["timezone"])
    calendar = fake_google.calendars_of("user-a")[0]
    events = fake_google.live_events(calendar.id)
    assert len(events) == 5
    for event, name in zip(events, ["fajr", "dhuhr", "asr", "maghrib", "isha"]):
        start = datetime.fromisoformat(event["start"]["dateTime"])
        end = datetime.fromisoformat(event["end"]["dateTime"])
        assert start == getattr(expected, name).time
        assert start.date() == day
        assert event["start"]["dateTime"].endswith(offset)
        assert event["end"]["dateTime"].endswith(offset)
        assert end - start == timedelta(minutes=MINUTES[name])


def test_spring_forward_dhuhr_is_an_hour_later_on_the_clock(client, fake_google, set_today, db):
    """Solar noon barely moves in a day, so Dhuhr's clock time should jump by about 1 hour."""
    sign_in(client, fake_google)
    save_setup(db, location=(TORONTO["latitude"], TORONTO["longitude"]))
    times = {}
    for day in (date(2026, 3, 7), date(2026, 3, 8)):
        set_today(day)
        dhuhr = client.post("/prayers/today").json()["events"][1]
        times[day] = datetime.fromisoformat(dhuhr["starts_at"])

    clock_difference = (
        datetime.combine(date.min, times[date(2026, 3, 8)].time())
        - datetime.combine(date.min, times[date(2026, 3, 7)].time())
    )
    assert timedelta(minutes=58) <= clock_difference <= timedelta(minutes=61)
