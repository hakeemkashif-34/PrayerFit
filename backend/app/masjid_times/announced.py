"""Times a masjid announced that its MAWAQIT page may not show yet.

Why: KMA announced new iqamah and Jumuah times for when the clocks fall
back on November 1, 2026, but its MAWAQIT page still showed the old Isha
and Jumuah times. A masjid's own announcement is its published source, so
it can be used, as long as it's written down where it gets reviewed.

Each masjid gets one JSON file in announced/, like announced/kma.json.
Changes go through a PR, the same as code. The file says:
1. label: the source shown on Settings and in each event's source, like
   "KMA announcement".
2. mawaqit_ids: the masjid's MAWAQIT IDs, as masjid_sources saves them
   ("id/9793" for a share link, "kma-masjid-ottawa" for a page link). This
   is how a file finds its masjid without a database ID, which is different
   on my laptop and on the server.
3. entries: each with a start date, an end date (both included), and
   iqamah times, Jumuah times, or both.

An iqamah is a clock time ("12:30", 24-hour) or an offset ("adhan + 30",
"sunset + 5"). Jumuah is a list of up to 3 clock times, used on every
Friday in the entry's range.

Inside an entry's range, its times win over MAWAQIT. Outside it, nothing
changes. Only iqamah and Jumuah change. Adhan times for home prayers never
do. Two entries giving the same prayer on the same date is a mistake, so
the whole file is refused.

A file that can't be read or fails a check is logged and skipped. That
masjid falls back to MAWAQIT, then calculated times, as normal. One bad
file never affects another masjid.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path

from app.masjid_times.source import PRAYERS, JumuahTime

logger = logging.getLogger("app.masjid_times.announced")

ANNOUNCED_DIR = Path(__file__).resolve().parent / "announced"
FRIDAY = 4
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# "adhan + 30" or "sunset + 5". Spaces are optional.
OFFSET = re.compile(r"^(adhan|sunset)\s*\+\s*(\d{1,3})$")
# Over 2 hours after the adhan or sunset is almost surely a typo.
MAX_OFFSET_MINUTES = 120
MAX_JUMUAH = 3


class BadAnnouncement(ValueError):
    """A file that fails a check. The message names the file and the problem."""


@dataclass(frozen=True)
class Rule:
    """One announced iqamah: a clock time, or minutes after the adhan or sunset."""

    clock: time | None = None
    # "adhan" or "sunset" when clock is None.
    base: str | None = None
    minutes: int = 0

    def text(self) -> str:
        """"12:30", "30 minutes after the adhan", "5 minutes after sunset"."""
        if self.clock is not None:
            return self.clock.strftime("%H:%M")
        what = "the adhan" if self.base == "adhan" else "sunset"
        return f"{self.minutes} minute{'s' if self.minutes != 1 else ''} after {what}"


@dataclass(frozen=True)
class Entry:
    start: date
    end: date
    iqamah: dict[str, Rule] = field(default_factory=dict)
    jumuah: tuple[JumuahTime, ...] = ()

    def covers(self, local_date: date) -> bool:
        return self.start <= local_date <= self.end


@dataclass(frozen=True)
class AnnouncedDay:
    """What an announcement says for one date. Prayers it doesn't mention aren't in iqamah."""

    local_date: date
    iqamah: dict[str, Rule]
    # Empty when the date isn't a Friday or no entry gives Jumuah for it.
    jumuah: tuple[JumuahTime, ...]


@dataclass(frozen=True)
class Announcement:
    name: str  # the file name without .json, like "kma", for logs
    label: str  # like "KMA announcement"
    mawaqit_ids: tuple[str, ...]
    entries: tuple[Entry, ...]

    def day(self, local_date: date) -> AnnouncedDay | None:
        """That date's announced times, or None when no entry covers it."""
        found = [e for e in self.entries if e.covers(local_date)]
        if not found:
            return None
        iqamah = {name: rule for e in found for name, rule in e.iqamah.items()}
        friday = local_date.weekday() == FRIDAY
        jumuah = next((e.jumuah for e in found if e.jumuah), ()) if friday else ()
        if not iqamah and not jumuah:
            return None
        return AnnouncedDay(local_date, iqamah, jumuah)

    def range_covering(self, local_date: date) -> tuple[date, date] | None:
        """The earliest start and latest end of the entries covering a date, for Settings."""
        found = [e for e in self.entries if e.covers(local_date)]
        if not found:
            return None
        return min(e.start for e in found), max(e.end for e in found)


def _clock(value: object, what: str) -> time:
    if not isinstance(value, str) or not CLOCK.match(value.strip()):
        raise BadAnnouncement(f'{what} must be a 24-hour clock time like "13:40"')
    hour, minute = CLOCK.match(value.strip()).groups()
    return time(int(hour), int(minute))


def _rule(value: object, what: str) -> Rule:
    if isinstance(value, str) and (offset := OFFSET.match(value.strip())):
        minutes = int(offset.group(2))
        if minutes > MAX_OFFSET_MINUTES:
            raise BadAnnouncement(f"{what} is more than {MAX_OFFSET_MINUTES} minutes after {offset.group(1)}")
        return Rule(base=offset.group(1), minutes=minutes)
    try:
        return Rule(clock=_clock(value, what))
    except BadAnnouncement:
        raise BadAnnouncement(f'{what} must be a clock time like "12:30", or "adhan + 30", or "sunset + 5"') from None


def _date(value: object, what: str) -> date:
    try:
        return date.fromisoformat(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise BadAnnouncement(f'{what} must be a date like "2026-11-01"') from None


def _entry(raw: object, number: int) -> Entry:
    what = f"entry {number}"
    if not isinstance(raw, dict):
        raise BadAnnouncement(f"{what} must be an object")
    unknown = set(raw) - {"start", "end", "iqamah", "jumuah", "note"}
    if unknown:
        raise BadAnnouncement(f"{what} has unknown keys: {', '.join(sorted(unknown))}")
    start, end = _date(raw.get("start"), f"{what} start"), _date(raw.get("end"), f"{what} end")
    if end < start:
        raise BadAnnouncement(f"{what} ends before it starts")

    iqamah_raw = raw.get("iqamah") or {}
    if not isinstance(iqamah_raw, dict):
        raise BadAnnouncement(f"{what} iqamah must be an object")
    if set(iqamah_raw) - set(PRAYERS):
        raise BadAnnouncement(f"{what} iqamah has unknown prayers: {', '.join(sorted(set(iqamah_raw) - set(PRAYERS)))}")
    iqamah = {name: _rule(value, f"{what} {name}") for name, value in iqamah_raw.items()}

    jumuah_raw = raw.get("jumuah") or []
    if not isinstance(jumuah_raw, list) or len(jumuah_raw) > MAX_JUMUAH:
        raise BadAnnouncement(f"{what} jumuah must be a list of up to {MAX_JUMUAH} clock times")
    times = [_clock(value, f"{what} jumuah {n}") for n, value in enumerate(jumuah_raw, start=1)]
    if times != sorted(set(times)):
        raise BadAnnouncement(f"{what} jumuah times must be in order, earliest first")
    if times and not any((start + timedelta(days=n)).weekday() == FRIDAY for n in range((end - start).days + 1)):
        raise BadAnnouncement(f"{what} gives Jumuah times but has no Friday")
    if not iqamah and not times:
        raise BadAnnouncement(f"{what} has no iqamah or jumuah times")
    jumuah = tuple(JumuahTime(order, clock) for order, clock in enumerate(times, start=1))
    return Entry(start, end, iqamah, jumuah)


def _check_overlaps(entries: list[Entry]) -> None:
    """Refuse 2 entries that give the same prayer, or Jumuah, on the same date."""
    for i, first in enumerate(entries):
        for j, second in enumerate(entries[i + 1 :], start=i + 1):
            if first.end < second.start or second.end < first.start:
                continue
            same = set(first.iqamah) & set(second.iqamah)
            if first.jumuah and second.jumuah:
                same.add("jumuah")
            if same:
                raise BadAnnouncement(f"entries {i + 1} and {j + 1} both give {', '.join(sorted(same))} on the same dates")


def parse(data: object, name: str) -> Announcement:
    """One file's contents, checked. Raises BadAnnouncement."""
    if not isinstance(data, dict):
        raise BadAnnouncement("the file must be a JSON object")
    label = data.get("label")
    if not isinstance(label, str) or not label.strip():
        raise BadAnnouncement('label is missing, like "KMA announcement"')
    ids = data.get("mawaqit_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i.strip() for i in ids):
        raise BadAnnouncement('mawaqit_ids must be a list like ["id/9793"]')
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise BadAnnouncement("entries must be a list with at least 1 entry")
    entries = [_entry(raw, n) for n, raw in enumerate(raw_entries, start=1)]
    _check_overlaps(entries)
    return Announcement(name, label.strip(), tuple(i.strip() for i in ids), tuple(entries))


@lru_cache(maxsize=4)
def _load_dir(directory: Path) -> dict[str, Announcement]:
    """Every good file in the folder, by MAWAQIT ID. Read once per process."""
    found: dict[str, Announcement] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            announcement = parse(json.loads(path.read_text(encoding="utf-8")), path.stem)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, BadAnnouncement) as error:
            logger.error("Announced times in %s weren't used: %s", path.name, error)
            continue
        taken = [i for i in announcement.mawaqit_ids if i in found]
        if taken:
            logger.error("Announced times in %s weren't used: %s is already in another file", path.name, taken[0])
            continue
        for mawaqit_id in announcement.mawaqit_ids:
            found[mawaqit_id] = announcement
    return found


def announcement_for(*mawaqit_ids: str | None) -> Announcement | None:
    """The announcement for a masjid with any of these MAWAQIT IDs, or None.

    Never raises. Anything unexpected is logged and the masjid falls back to MAWAQIT.
    """
    try:
        loaded = _load_dir(ANNOUNCED_DIR)
    except Exception:  # noqa: BLE001
        logger.exception("Couldn't load announced times")
        return None
    return next((loaded[i] for i in mawaqit_ids if i and i in loaded), None)
