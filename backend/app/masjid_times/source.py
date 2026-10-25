"""The small interface every masjid times source follows.

The scheduler only talks to MasjidTimesSource. Adding another source later
(a masjid's own website, say) means writing one more adapter and adding it
to SOURCES, without touching the scheduler. If one source breaks, only the
masjids linked to it fall back to calculated times.
"""

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Protocol

import httpx2

PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha")


@dataclass(frozen=True)
class JumuahTime:
    """One Jumuah slot. order is 1, 2, or 3: MAWAQIT's jumua, jumua2, and jumua3.

    A user's pick is saved as the masjid and this order, not the clock
    time, since a masjid can move its 3rd Jumuah every week.
    """

    order: int
    time: time


def next_friday(today: date) -> date:
    """Today if it's a Friday, otherwise the coming one."""
    return today + timedelta(days=(4 - today.weekday()) % 7)


@dataclass(frozen=True)
class DayTimes:
    """One masjid's published times for one local date, as clock times in its time zone."""

    local_date: date
    adhan: dict[str, time]
    # None when the masjid didn't publish an iqamah for that prayer. Never made up.
    iqamah: dict[str, time | None]
    # In MAWAQIT's order. Only on the coming Friday: masjids update their
    # Jumuah times each week, so a later Friday's aren't published yet.
    jumuah: tuple[JumuahTime, ...] = field(default_factory=tuple)


class SourceError(Exception):
    """A fetch didn't give usable times. The message is safe to log: no addresses or user data."""


class SourceBlocked(SourceError):
    """The source said no (403) or slow down (429). Wait 24 hours before trying again."""


class SourceFailed(SourceError):
    """A timeout, a connection error, a server error, or a page that's too big."""


class SourceInvalid(SourceError):
    """The page was read, but its data failed a check, so none of it is used."""


class MasjidTimesSource(Protocol):
    # Saved in masjid_sources.source and shown in event descriptions.
    name: str
    label: str

    def fetch(self, http: httpx2.Client, external_id: str, today: date, days: int) -> list[DayTimes]:
        """Times for today and the next days - 1 local dates. Raises a SourceError."""
        ...


def get_source(name: str) -> MasjidTimesSource:
    # Imported here so adapters can import this module without a loop.
    from app.masjid_times.mawaqit import MawaqitSource

    sources: dict[str, MasjidTimesSource] = {"mawaqit": MawaqitSource()}
    return sources[name]
