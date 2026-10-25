"""Leave and arrival times for a masjid prayer.

Target = the iqamah (or the calculated start when there's no iqamah).
Arrival = target minus the user's "how early" minutes.
Leave = arrival minus the drive time, rounded down to the minute.

All of it is counted in UTC and turned back into local time at the end,
so a daylight saving change in between can't add or lose an hour.

Example: Isha iqamah 8:15 pm, 5 minutes early, 14 minute drive.
Arrive 8:10 pm, leave 7:56 pm.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class MasjidTrip:
    leave_at: datetime | None  # None when the drive time is unknown
    arrive_at: datetime
    target: datetime


def trip(target: datetime, early_minutes: int, drive_seconds: int | None) -> MasjidTrip:
    zone = target.tzinfo
    arrive = target.astimezone(UTC) - timedelta(minutes=early_minutes)
    leave = None
    if drive_seconds is not None:
        leave = (arrive - timedelta(seconds=drive_seconds)).replace(second=0, microsecond=0)
        leave = leave.astimezone(zone)
    return MasjidTrip(leave_at=leave, arrive_at=arrive.astimezone(zone), target=target)


def drive_minutes(seconds: int) -> int:
    """What the description says, rounded up: a 13.5 minute drive is "14 min"."""
    return -(-seconds // 60)
