"""Work out one day's events: which time each prayer uses, and its drive block.

plan_day is a pure function. It gets the calculated times, the masjid's
published times, and the drive times as arguments, and returns the events.
It never calls a database or a website, so every case is easy to test.

Which time each prayer uses:
1. At the masjid: the masjid's iqamah. If there's none that day, or the
   masjid's times couldn't be confirmed in the last 24 hours, the
   calculated start time. An iqamah is never made up.
2. At home: the main masjid's adhan time, if it's linked and its times are
   usable. Otherwise the calculated time.
3. Friday with Jumuah masjids: Dhuhr becomes Jumuah at the slot the
   Jumuah picker chose. If no slot is picked, Dhuhr follows the weekly grid.

Busy times come first. It works in 2 passes:
1. Masjid prayers: at the masjid only if the drive, the "how early"
   minutes, and the prayer block are all free.
2. Every other prayer: at its normal time if that's free. Otherwise in the
   earliest free gap of at least 10 minutes before its time ends, avoiding
   the events pass 1 planned. No gap means a clash (see fit_prayers.py).

Events have no description, except a moved prayer (which says when the
user is busy) and a clash. Where each time came from is saved in
source_description and shown on the Settings page instead.

Every masjid prayer gets 2 events: a drive block from the leave time to
the arrival time, then the prayer block at the target time. Fajr, Asr, and
Maghrib blocks are 10 minutes, Dhuhr and Isha 15, and Jumuah uses the
masjid's own length (45 minutes when it isn't set).
No drive time means no drive block.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.event_times import trip
from app.fit_prayers import Fit, PrayerWindow, fit_prayer, masjid_is_free, prayer_windows
from app.jumuah import DEFAULT_JUMUAH_MINUTES, JumuahChoice, JumuahSlot, choose_jumuah
from app.masjid_times.store import MasjidTimes
from app.models import Masjid
from app.prayer_sync import ASR_NAMES, METHOD_NAMES, PRAYER_LENGTHS, PRAYER_TITLES, PRAYERS, event_end, source_description
from app.prayer_times import DailyPrayerTimes, PrayerTime, calculate_prayer_times
from app.user_settings import Setup

FRIDAY = 4
# A fixed namespace, so a drive block's ID only depends on its prayer event's ID.
DRIVE_NAMESPACE = uuid.UUID("5b0d6f5e-8c1a-4e8e-9a43-1f6b2f1c7d10")


def drive_event_id(prayer_event_id: uuid.UUID) -> uuid.UUID:
    """The drive block's own stable ID, made from its prayer event's ID.

    Running again gives the same ID, so Google refuses a copy (409) the
    same way it does for prayer events.
    """
    return uuid.uuid5(DRIVE_NAMESPACE, f"drive:{prayer_event_id}")


@dataclass(frozen=True)
class PlannedEvent:
    local_date: date
    prayer: str
    starts_at: datetime
    ends_at: datetime
    time_zone: str
    source_description: str
    place: str
    masjid_id: uuid.UUID | None
    summary: str
    description: str
    # "prayer" or "drive"
    kind: str = "prayer"
    color_id: str | None = None
    reminder_minutes: int | None = None
    # "normal", "moved", or "clash". Saved, but not sent to Google.
    fit: str = "normal"

    def values(self) -> dict:
        return {
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "time_zone": self.time_zone,
            "source_description": self.source_description,
            "place": self.place,
            "masjid_id": self.masjid_id,
            "summary": self.summary,
            "description": self.description,
            "color_id": self.color_id,
            "reminder_minutes": self.reminder_minutes,
            "fit": self.fit,
        }


def _short_clock(moment: datetime) -> str:
    """7:23 pm"""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02} {'am' if moment.hour < 12 else 'pm'}"


def method_text(prayer: PrayerTime) -> str:
    """"ISNA, standard Asr", plus the high latitude rule when one was used."""
    parts = [METHOD_NAMES[prayer.method], ASR_NAMES[prayer.asr_method]]
    if prayer.high_latitude_rule:
        parts.append(prayer.high_latitude_rule.value.replace("_", " ") + " rule")
    return ", ".join(parts)


def date_text(moment: datetime, time_zone: str) -> str:
    """Oct 25, 2026"""
    local = moment.astimezone(ZoneInfo(time_zone))
    return f"{local:%b} {local.day}, {local.year}"


def at_local(local_date: date, clock: time, time_zone: str) -> datetime:
    """A masjid's clock time on a local date. The zone decides the offset for
    that date, so daylight saving is right without adding any hours."""
    return datetime.combine(local_date, clock, tzinfo=ZoneInfo(time_zone))


def _updated(times: MasjidTimes, user_zone: str) -> str:
    changed = times.last_changed_at or times.last_success_at
    return date_text(changed, user_zone)


def duration_text(minutes: int) -> str:
    """"42 minutes", "1 hour", "1 hour 12 minutes"."""
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if rest or not hours:
        parts.append(f"{rest} minute{'s' if rest != 1 else ''}")
    return " ".join(parts)


def moved_text(title: str, start: datetime, placed: datetime) -> str:
    """How far after the prayer's start time it was placed. The app only knows
    when the user is busy, never what the event is."""
    minutes = round((placed.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60)
    if minutes == 0:
        when = f"at {title}'s start time"
    elif minutes > 0:
        when = f"{duration_text(minutes)} after {title}'s start time"
    else:
        when = f"{duration_text(-minutes)} before {title}'s start time"
    return f"Moved because of an event in your calendar ({when})."


def clash_text(title: str) -> str:
    return f"Your event covers all of {title}'s time today, so figure out a way to fit it in."


@dataclass(frozen=True)
class MasjidContext:
    """Everything plan_day needs to know about one of the user's masjids."""

    masjid: Masjid
    label: str  # "KMA" or the masjid's name
    time_zone: str  # the masjid's own time zone, for its published times
    times: MasjidTimes | None  # None when it isn't linked to a source
    drive_seconds: int | None
    # How long this masjid's Jumuah takes. None means unknown, so 45 is used.
    jumuah_minutes: int | None = None

    @property
    def jumuah_length(self) -> int:
        return self.jumuah_minutes or DEFAULT_JUMUAH_MINUTES


def _masjid_events(
    setup: Setup,
    local_date: date,
    prayer: str,
    title: str,
    where: MasjidContext,
    target: datetime,
    source: str,
    user_zone: str,
    length: timedelta | None = None,
    early: int | None = None,
    fit: str = "normal",
    description: str = "",
) -> list[PlannedEvent]:
    """The drive block (when the drive time is known) and the prayer block."""
    events = []
    early = setup.arrive_early_minutes if early is None else early
    planned = trip(target, early, where.drive_seconds)
    if planned.leave_at is not None and planned.leave_at < planned.arrive_at:
        events.append(
            PlannedEvent(
                local_date=local_date,
                prayer=prayer,
                kind="drive",
                starts_at=planned.leave_at,
                ends_at=planned.arrive_at,
                time_zone=user_zone,
                source_description="OpenRouteService",
                place="masjid",
                masjid_id=where.masjid.id,
                summary=f"Drive to {where.label}",
                description="",
                color_id=setup.drive_color_id,
                # A popup when it's time to leave.
                reminder_minutes=0,
            )
        )
    events.append(
        PlannedEvent(
            local_date=local_date,
            prayer=prayer,
            starts_at=target,
            ends_at=event_end(target, length or PRAYER_LENGTHS[prayer]),
            time_zone=user_zone,
            source_description=source,
            place="masjid",
            masjid_id=where.masjid.id,
            summary=f"{title} at {where.label}",
            description=description,
            color_id=setup.prayer_color_id,
            fit=fit,
        )
    )
    return events


def jumuah_slots(jumuah: list[MasjidContext], local_date: date) -> list[JumuahSlot]:
    """Every Jumuah slot from the user's Jumuah masjids on this Friday."""
    slots = []
    for context in jumuah:
        day = context.times.usable_day(local_date) if context.times else None
        for slot in day.jumuah if day else ():
            slots.append(JumuahSlot(context.masjid.id, slot.order, at_local(local_date, slot.time, context.time_zone)))
    return slots


def choose(
    setup: Setup, local_date: date, jumuah: list[MasjidContext], busy: list[tuple[datetime, datetime]]
) -> JumuahChoice:
    """The Jumuah for this Friday, using the user's pick and their busy times."""
    return choose_jumuah(
        jumuah_slots(jumuah, local_date),
        setup.jumuah_pick,
        {c.masjid.id: c.drive_seconds for c in jumuah},
        setup.jumuah_arrive_early_minutes,
        {c.masjid.id: c.jumuah_length for c in jumuah},
        busy,
        listed_order=[c.masjid.id for c in jumuah],
    )


def _jumuah(
    setup: Setup,
    local_date: date,
    jumuah: list[MasjidContext],
    user_zone: str,
    busy: list[tuple[datetime, datetime]],
    upcoming_friday: date | None,
) -> list[PlannedEvent] | None:
    """Friday's Jumuah events, or None when there's no Jumuah to put in.

    MAWAQIT only holds this week's Jumuah times, so only the coming Friday
    gets them. Other Fridays follow the weekly grid for Dhuhr.
    """
    if local_date != upcoming_friday:
        return None
    choice = choose(setup, local_date, jumuah, busy)
    if choice.window is None:
        return None
    where = next(c for c in jumuah if c.masjid.id == choice.window.slot.masjid_id)
    source = f"{where.label} Jumuah ({where.times.source_label}, updated {_updated(where.times, user_zone)})"
    description = ""
    if choice.fit == "moved":
        # Jumuah has no adhan of its own, so its start time is the day's 1st Jumuah.
        first = min(slot.starts_at for slot in jumuah_slots(jumuah, local_date))
        description = moved_text("Jumuah", first, choice.window.slot.starts_at)
    elif choice.fit == "clash":
        description = clash_text("Jumuah")
    return _masjid_events(
        setup, local_date, "dhuhr", "Jumuah", where, choice.window.slot.starts_at, source, user_zone,
        timedelta(minutes=where.jumuah_length), early=setup.jumuah_arrive_early_minutes, fit=choice.fit,
        description=description,
    )


def _home_time(
    name: str, local_date: date, day: DailyPrayerTimes, main: MasjidContext | None, main_day
) -> tuple[datetime, str]:
    """A prayer's start at home, and where it came from."""
    if main_day is not None:
        target = at_local(local_date, main_day.adhan[name], main.time_zone)
        return target, f"{main.label} adhan time ({main.times.source_label})"
    calculated: PrayerTime = getattr(day, name)
    return calculated.time, source_description(calculated)


def _masjid_time(
    name: str, local_date: date, day: DailyPrayerTimes, main: MasjidContext, main_day, user_zone: str
) -> tuple[datetime, str]:
    """A masjid prayer's target (the iqamah, or the calculated start), and where it came from."""
    calculated: PrayerTime = getattr(day, name)
    iqamah = main_day.iqamah.get(name) if main_day else None
    if iqamah is not None:
        source = f"{main.label} iqamah ({main.times.source_label}, updated {_updated(main.times, user_zone)})"
        return at_local(local_date, iqamah, main.time_zone), source
    return calculated.time, f"Calculated start time ({method_text(calculated)}). {main.label}'s iqamah time isn't available."


def _windows(
    local_date: date,
    day: DailyPrayerTimes,
    next_day: DailyPrayerTimes | None,
    main: MasjidContext | None,
    main_day,
) -> dict[str, PrayerWindow]:
    """Each prayer's window, from the same start times home prayers use."""
    starts = {name: _home_time(name, local_date, day, main, main_day)[0] for name in PRAYERS}
    next_date = local_date + timedelta(days=1)
    if next_day is None:
        next_day = calculate_prayer_times(day.latitude, day.longitude, next_date, day.timezone, day.method, day.asr_method)
    next_main = main.times.usable_day(next_date) if main and main.times else None
    next_fajr = _home_time("fajr", next_date, next_day, main, next_main)[0]
    # MAWAQIT's sunrise isn't saved, so Fajr ends at the calculated sunrise
    # (rounded down, the safe side).
    return prayer_windows(starts, day.sunrise.time, next_fajr)


def _home_event(
    setup: Setup, local_date: date, name: str, fit: Fit, source: str, summary: str, description: str, user_zone: str
) -> PlannedEvent:
    return PlannedEvent(
        local_date=local_date,
        prayer=name,
        starts_at=fit.starts_at,
        ends_at=event_end(fit.starts_at, fit.length),
        time_zone=user_zone,
        source_description=source,
        place="home",
        masjid_id=None,
        summary=summary,
        description=description,
        color_id=setup.prayer_color_id,
        fit=fit.kind,
    )


def plan_day(
    setup: Setup,
    local_date: date,
    day: DailyPrayerTimes,
    main: MasjidContext | None,
    jumuah: list[MasjidContext],
    busy: list[tuple[datetime, datetime]] | None = None,
    upcoming_friday: date | None = None,
    next_day: DailyPrayerTimes | None = None,
    now: datetime | None = None,
) -> list[PlannedEvent]:
    """Every event for one day: 5 prayer blocks, plus a drive block before each masjid prayer.

    busy: the user's busy times. Empty means nothing moves.
    next_day: tomorrow's calculated times, for when Isha ends.
    now: a moved prayer never starts before it.
    """
    user_zone = day.timezone
    busy = busy or []
    main_day = main.times.usable_day(local_date) if main and main.times else None
    windows = _windows(local_date, day, next_day, main, main_day) if busy else None

    friday: list[PlannedEvent] = []
    if local_date.weekday() == FRIDAY and jumuah:
        friday = _jumuah(setup, local_date, jumuah, user_zone, busy, upcoming_friday) or []
    names = [n for n in PRAYERS if not (n == "dhuhr" and friday)]  # Jumuah took Dhuhr's place

    # Pass 1: masjid prayers whose whole trip is free.
    at_masjid: dict[str, list[PlannedEvent]] = {}
    # The normal time (the iqamah, or the start), and where it came from.
    not_at_masjid: dict[str, tuple[datetime, str]] = {}
    for name in names:
        if setup.place_for(local_date.weekday(), name) != "masjid":
            continue
        target, source = _masjid_time(name, local_date, day, main, main_day, user_zone)
        length = PRAYER_LENGTHS[name]
        if masjid_is_free(target, setup.arrive_early_minutes, main.drive_seconds, length, busy):
            at_masjid[name] = _masjid_events(setup, local_date, name, PRAYER_TITLES[name], main, target, source, user_zone)
        else:
            not_at_masjid[name] = (target, source)

    # Pass 2: every other prayer. A moved one avoids the app's own events too.
    taken = [(e.starts_at, e.ends_at) for e in friday + [e for events in at_masjid.values() for e in events]]
    placed: dict[str, PlannedEvent] = {}
    for name in names:
        if name in at_masjid:
            continue
        length = PRAYER_LENGTHS[name]
        if name in not_at_masjid:
            normal, source = not_at_masjid[name]
        else:
            normal, source = _home_time(name, local_date, day, main, main_day)
        fit = fit_prayer(windows[name], normal, length, busy, taken, now) if windows else Fit("normal", normal, length)
        title = PRAYER_TITLES[name]
        if fit.kind == "normal" and name not in not_at_masjid:
            # Just the prayer's name. Only masjid prayers say where.
            event = _home_event(setup, local_date, name, fit, source, title, "", user_zone)
        elif fit.kind == "clash":
            event = _home_event(setup, local_date, name, fit, source, f"{title} (clash)", clash_text(title), user_zone)
        else:
            # Moved in time, or a masjid prayer prayed at home instead.
            moved = Fit("moved", fit.starts_at, fit.length)
            description = moved_text(title, windows[name].starts_at, fit.starts_at)
            event = _home_event(setup, local_date, name, moved, source, title, description, user_zone)
        taken.append((event.starts_at, event.ends_at))
        placed[name] = event

    planned = list(friday)
    for name in names:
        planned.extend(at_masjid.get(name) or [placed[name]])
    return planned
