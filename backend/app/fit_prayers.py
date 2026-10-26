"""Fit a prayer around the user's busy times.

These are pure functions: everything comes in as arguments, nothing is
saved or sent, so every case is easy to test.

The rule: the user's events come first. A prayer stays at its normal time
when that time is free. Otherwise it goes in the earliest free gap of at
least 10 minutes, from the start of the prayer's time to its end. If
there's no such gap, it stays at its normal time, flagged as a clash.

All the maths is done in UTC. Python compares 2 times in the same ZoneInfo
by their wall clocks, which is wrong on a daylight saving day.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.event_times import trip

# Every prayer needs at least this long. A shorter gap is skipped.
MIN_LENGTH = timedelta(minutes=10)

Busy = list[tuple[datetime, datetime]]


@dataclass(frozen=True)
class PrayerWindow:
    """When a prayer's time starts and ends."""

    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Fit:
    # "normal" (at its normal time), "moved", or "clash" (no free time at all)
    kind: str
    starts_at: datetime
    length: timedelta

    @property
    def ends_at(self) -> datetime:
        return _back((_utc(self.starts_at) + self.length), self.starts_at)


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _back(moment: datetime, like: datetime) -> datetime:
    """A UTC time back in the same time zone as `like`."""
    return moment.astimezone(like.tzinfo)


def _floor_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _ceil_minute(moment: datetime) -> datetime:
    floored = _floor_minute(moment)
    return floored if floored == moment else floored + timedelta(minutes=1)


def midnight(maghrib: datetime, next_fajr: datetime) -> datetime:
    """Halfway between Maghrib and the next day's Fajr, when Isha's time ends.

    Rounded down to the minute, since ending a little early is the safe side.
    """
    halfway = _utc(maghrib) + (_utc(next_fajr) - _utc(maghrib)) / 2
    return _back(_floor_minute(halfway), maghrib)


def prayer_windows(starts: dict[str, datetime], sunrise: datetime, next_fajr: datetime) -> dict[str, PrayerWindow]:
    """Each prayer's window. Fajr ends at sunrise, each of the next 3 at the
    following prayer, and Isha at midnight."""
    return {
        "fajr": PrayerWindow(starts["fajr"], sunrise),
        "dhuhr": PrayerWindow(starts["dhuhr"], starts["asr"]),
        "asr": PrayerWindow(starts["asr"], starts["maghrib"]),
        "maghrib": PrayerWindow(starts["maghrib"], starts["isha"]),
        "isha": PrayerWindow(starts["isha"], midnight(starts["maghrib"], next_fajr)),
    }


def is_free(start: datetime, end: datetime, busy: Busy) -> bool:
    """True when nothing in busy overlaps start to end. Touching ends don't count."""
    start, end = _utc(start), _utc(end)
    return not any(start < _utc(b_end) and _utc(b_start) < end for b_start, b_end in busy)


def _merged(busy: Busy) -> list[tuple[datetime, datetime]]:
    """Busy times in UTC, sorted, with overlapping ones joined."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted((_utc(s), _utc(e)) for s, e in busy):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def earliest_gap(
    window: PrayerWindow, max_length: timedelta, busy: Busy, not_before: datetime | None = None
) -> tuple[datetime, timedelta] | None:
    """The earliest free gap of at least 10 minutes in the window, and the
    block's length: the full length, or shorter to fit the gap. None if there's no gap."""
    cursor = _utc(window.starts_at)
    if not_before is not None:
        # A moved prayer never goes in the past.
        cursor = max(cursor, _ceil_minute(_utc(not_before)))
    window_end = _utc(window.ends_at)
    for busy_start, busy_end in _merged(busy) + [(window_end, window_end)]:
        if busy_end <= cursor:
            continue
        gap_end = min(busy_start, window_end)
        if gap_end - cursor >= MIN_LENGTH:
            return _back(cursor, window.starts_at), min(max_length, gap_end - cursor)
        cursor = max(cursor, busy_end)
        if cursor >= window_end:
            break
    return None


def fit_prayer(
    window: PrayerWindow,
    normal: datetime,
    max_length: timedelta,
    busy: Busy,
    taken: Busy = (),
    not_before: datetime | None = None,
) -> Fit:
    """Where one prayer goes.

    busy: the user's own events. Only these decide whether the normal time is free.
    taken: the app's own events already planned that day. A moved prayer avoids them too.
    not_before: now. A moved prayer never starts before it.
    """
    if is_free(normal, _back(_utc(normal) + max_length, normal), busy):
        return Fit("normal", normal, max_length)
    gap = earliest_gap(window, max_length, [*busy, *taken], not_before)
    if gap is not None:
        return Fit("moved", gap[0], gap[1])
    return Fit("clash", normal, max_length)


def masjid_is_free(
    target: datetime, early_minutes: int, drive_seconds: int | None, length: timedelta, busy: Busy
) -> bool:
    """True when the drive, the "how early" minutes, and the prayer block are all free.

    Without a drive time, it checks from arriving to the end of the prayer.
    """
    planned = trip(target, early_minutes, drive_seconds)
    start = planned.leave_at or planned.arrive_at
    return is_free(start, _back(_utc(target) + length, target), busy)
