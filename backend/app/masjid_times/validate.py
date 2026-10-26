"""Checks on a source's times before any of them are saved.

A wrong time means a missed prayer, so one bad value rejects the whole
fetch. The last good times stay in use, and the failure is logged.
"""

import re
from datetime import time

from app.masjid_times.source import PRAYERS, DayTimes, SourceInvalid

# 24-hour clock, like "05:42" or "20:15". "5:42" is allowed too.
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# Minutes after adhan, like "+10".
AFTER_ADHAN = re.compile(r"^\+(\d{1,3})$")
MAX_IQAMAH_AFTER_ADHAN = 90


def minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def clock_time(value: object, what: str) -> time:
    """"20:15" -> 20:15. Anything else (25:00, "abc", None) fails the fetch."""
    if not isinstance(value, str) or not CLOCK.match(value.strip()):
        raise SourceInvalid(f"{what} isn't a clock time")
    hour, minute = CLOCK.match(value.strip()).groups()
    return time(int(hour), int(minute))


def iqamah_time(value: object, adhan: time, what: str) -> time | None:
    """An iqamah as a clock time ("20:15") or minutes after adhan ("+10").

    Empty means the masjid didn't publish one, so it stays empty. "+0" is
    iqamah at the adhan time: KMA uses it on the days its set Asr or Isha
    time would come before the adhan (checked against KMA's MAWAQIT screen).
    """
    if value is None or (isinstance(value, str) and value.strip() in ("", "-")):
        return None
    if isinstance(value, str) and (after := AFTER_ADHAN.match(value.strip())):
        total = minutes(adhan) + int(after.group(1))
        if total >= 24 * 60:
            # Past midnight would be the next day. Refuse it rather than guess.
            raise SourceInvalid(f"{what} is after midnight")
        return time(total // 60, total % 60)
    return clock_time(value, what)


def check_day(day: DayTimes) -> None:
    """Every prayer present, iqamah not before adhan, and at most 90 minutes after."""
    for prayer in PRAYERS:
        if prayer not in day.adhan:
            raise SourceInvalid(f"{day.local_date} has no {prayer} adhan")
        iqamah = day.iqamah.get(prayer)
        if iqamah is None:
            continue
        gap = minutes(iqamah) - minutes(day.adhan[prayer])
        if gap < 0:
            raise SourceInvalid(f"{day.local_date} {prayer} iqamah is before adhan")
        if gap > MAX_IQAMAH_AFTER_ADHAN:
            raise SourceInvalid(f"{day.local_date} {prayer} iqamah is more than {MAX_IQAMAH_AFTER_ADHAN} minutes after adhan")
    order = [minutes(day.adhan[p]) for p in PRAYERS]
    if order != sorted(order):
        raise SourceInvalid(f"{day.local_date} adhan times are out of order")
