"""Work out one day's events: which time each prayer uses, and its drive block.

plan_day is a pure function. It gets the calculated times, the masjid's
published times, and the drive times as arguments, and returns the events.
It never calls a database or a website, so every case is easy to test.

Which time each prayer uses:
1. At the masjid: the masjid's iqamah. If there's none that day, or the
   masjid's times are over 7 days old, the calculated start time, and the
   description says so. An iqamah is never made up.
2. At home: the main masjid's adhan time, if it's linked and its times are
   usable. Otherwise the calculated time, as before.
3. Friday with Jumuah masjids: Dhuhr becomes Jumuah at the slot the
   Jumuah picker chose. If no slot is picked, Dhuhr follows the weekly grid.

Busy times come first (milestone 6). It works in 2 passes:
1. Masjid prayers: at the masjid only if the drive, the "how early"
   minutes, and the prayer block are all free.
2. Every other prayer: at its normal time if that's free. Otherwise in the
   earliest free gap of at least 10 minutes before its time ends, avoiding
   the events pass 1 planned. No gap means a clash (see fit_prayers.py).
A prayer that busy times didn't touch keeps exactly the same title and
description as before, so it isn't sent to Google again.

Every masjid prayer gets 2 events: a drive block from the leave time to
the arrival time, then the prayer block at the target time. Fajr, Asr, and
Maghrib blocks are 10 minutes, Dhuhr and Isha 15, and Jumuah uses the
masjid's own length (45 minutes when it isn't set).
No drive time means no drive block.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.event_times import drive_minutes, trip
from app.fit_prayers import Fit, PrayerWindow, fit_prayer, masjid_is_free, prayer_windows
from app.jumuah import DEFAULT_JUMUAH_MINUTES, JumuahChoice, JumuahSlot, choose_jumuah
from app.masjid_times.freshness import Freshness
from app.masjid_times.store import MasjidTimes
from app.models import Masjid
from app.prayer_sync import (
    ASR_NAMES,
    METHOD_NAMES,
    PRAYER_LENGTHS,
    PRAYER_TITLES,
    PRAYERS,
    event_end,
    source_description,
)
from app.prayer_times import DailyPrayerTimes, PrayerTime, calculate_prayer_times
from app.prayer_times.methods import METHODS
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


def _clock(moment: datetime) -> str:
    """12:46:57 pm"""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02}:{moment.second:02} {'am' if moment.hour < 12 else 'pm'}"


def dhuhr_note(day: DailyPrayerTimes) -> str:
    """Why Dhuhr is a minute or so after solar noon."""
    offset = METHODS[day.method].dhuhr_minutes_after_noon
    noon = (day.dhuhr.exact_time - timedelta(minutes=offset)).astimezone(ZoneInfo(day.timezone))
    if offset == 0:
        return f"Starts at solar noon ({_clock(noon)}), rounded up to the minute."
    return (
        f"Starts {offset} minute after solar noon ({_clock(noon)}), once the whole sun "
        "has passed overhead, then rounded up to the minute."
    )


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


def _stale_note(times: MasjidTimes | None, user_zone: str) -> list[str]:
    if times is None:
        return []
    if times.freshness is Freshness.STALE:
        return [f"{times.source_label} times may be out of date (last updated {date_text(times.last_success_at, user_zone)})"]
    if times.freshness is Freshness.TOO_OLD:
        return [f"{times.source_label} times are more than 7 days old, so they aren't used."]
    return []


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
    lines: list[str],
    aim: str,
    user_zone: str,
    length: timedelta | None = None,
    early: int | None = None,
    fit: str = "normal",
) -> list[PlannedEvent]:
    """The drive block (when the drive time is known) and the prayer block."""
    events = []
    early = setup.arrive_early_minutes if early is None else early
    planned = trip(target, early, where.drive_seconds)
    if planned.leave_at is not None and planned.leave_at < planned.arrive_at:
        arriving = f"Arriving {early} min before {aim}." if early else f"Arriving at {aim} time."
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
                description=(
                    f"{drive_minutes(where.drive_seconds)} min drive (OpenRouteService, no live traffic). {arriving}"
                ),
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
            source_description=lines[0],
            place="masjid",
            masjid_id=where.masjid.id,
            summary=f"{title} at {where.label}",
            description="\n".join(lines),
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
) -> tuple[list[PlannedEvent] | None, str | None]:
    """Friday's Jumuah events, or (None, why not) when there's no Jumuah to put in."""
    if local_date != upcoming_friday:
        # MAWAQIT only holds this week's Jumuah times. A later read covers this Friday.
        return None, "This Friday's Jumuah times aren't published yet, so this follows your weekly prayers."
    choice = choose(setup, local_date, jumuah, busy)
    if choice.window is None:
        return None, "Jumuah times aren't available for your Jumuah masjids, so this follows your weekly prayers."
    where = next(c for c in jumuah if c.masjid.id == choice.window.slot.masjid_id)
    lines = [
        f"{where.label} Jumuah ({where.times.source_label}, updated {_updated(where.times, user_zone)})",
        *_stale_note(where.times, user_zone),
        choice.reason,
    ]
    if where.jumuah_minutes is None:
        lines.append(f"End time is estimated ({DEFAULT_JUMUAH_MINUTES} minutes).")
    events = _masjid_events(
        setup, local_date, "dhuhr", "Jumuah", where, choice.window.slot.starts_at, lines, "Jumuah", user_zone,
        timedelta(minutes=where.jumuah_length), early=setup.jumuah_arrive_early_minutes, fit=choice.fit,
    )
    return events, None


MOVED = "Moved because of an event in your calendar."


def _home_time(
    name: str, local_date: date, day: DailyPrayerTimes, main: MasjidContext | None, main_day, user_zone: str
) -> tuple[datetime, list[str]]:
    """A prayer's start at home, and where it came from."""
    if main_day is not None:
        target = at_local(local_date, main_day.adhan[name], main.time_zone)
        return target, [f"{main.label} adhan time ({main.times.source_label})", *_stale_note(main.times, user_zone)]
    # The same as before milestone 5, so these events don't change.
    calculated: PrayerTime = getattr(day, name)
    lines = [source_description(calculated)]
    if name == "dhuhr":
        lines.append(dhuhr_note(day))
    return calculated.time, lines


def _masjid_time(
    name: str, local_date: date, day: DailyPrayerTimes, main: MasjidContext, main_day, user_zone: str
) -> tuple[datetime, list[str], str]:
    """A masjid prayer's target (the iqamah, or the calculated start), where it came from, and what the drive aims for."""
    calculated: PrayerTime = getattr(day, name)
    iqamah = main_day.iqamah.get(name) if main_day else None
    if iqamah is not None:
        lines = [
            f"{main.label} iqamah ({main.times.source_label}, updated {_updated(main.times, user_zone)})",
            *_stale_note(main.times, user_zone),
        ]
        return at_local(local_date, iqamah, main.time_zone), lines, "iqamah"
    lines = [
        f"Calculated start time ({method_text(calculated)}). {main.label}'s iqamah time isn't available.",
        *_stale_note(main.times, user_zone),
    ]
    if name == "dhuhr":
        lines.append(dhuhr_note(day))
    return calculated.time, lines, "the calculated start"


def _windows(
    local_date: date,
    day: DailyPrayerTimes,
    next_day: DailyPrayerTimes | None,
    main: MasjidContext | None,
    main_day,
    user_zone: str,
) -> dict[str, PrayerWindow]:
    """Each prayer's window, from the same start times home prayers use."""
    starts = {name: _home_time(name, local_date, day, main, main_day, user_zone)[0] for name in PRAYERS}
    next_date = local_date + timedelta(days=1)
    if next_day is None:
        next_day = calculate_prayer_times(day.latitude, day.longitude, next_date, day.timezone, day.method, day.asr_method)
    next_main = main.times.usable_day(next_date) if main and main.times else None
    next_fajr = _home_time("fajr", next_date, next_day, main, next_main, user_zone)[0]
    # MAWAQIT's sunrise isn't saved, so Fajr ends at the calculated sunrise
    # (rounded down, the safe side).
    return prayer_windows(starts, day.sunrise.time, next_fajr)


def _window_line(name: str, window: PrayerWindow) -> str:
    """For example: Isha's time is 7:23 pm to 12:41 am."""
    return f"{PRAYER_TITLES[name]}'s time is {_short_clock(window.starts_at)} to {_short_clock(window.ends_at)}."


def _home_event(
    setup: Setup, local_date: date, name: str, fit: Fit, lines: list[str], source: str, summary: str, user_zone: str
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
        description="\n".join(lines),
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
    windows = _windows(local_date, day, next_day, main, main_day, user_zone) if busy else None

    friday: list[PlannedEvent] = []
    jumuah_note = None
    if local_date.weekday() == FRIDAY and jumuah:
        events, jumuah_note = _jumuah(setup, local_date, jumuah, user_zone, busy, upcoming_friday)
        friday = events or []
    names = [n for n in PRAYERS if not (n == "dhuhr" and friday)]  # Jumuah took Dhuhr's place

    def extra(name: str) -> list[str]:
        return [jumuah_note] if name == "dhuhr" and jumuah_note else []

    # Pass 1: masjid prayers whose whole trip is free.
    at_masjid: dict[str, list[PlannedEvent]] = {}
    not_at_masjid: dict[str, tuple[datetime, list[str]]] = {}
    for name in names:
        if setup.place_for(local_date.weekday(), name) != "masjid":
            continue
        target, lines, aim = _masjid_time(name, local_date, day, main, main_day, user_zone)
        if masjid_is_free(target, setup.arrive_early_minutes, main.drive_seconds, PRAYER_LENGTHS[name], busy):
            at_masjid[name] = _masjid_events(
                setup, local_date, name, PRAYER_TITLES[name], main, target, lines + extra(name), aim, user_zone
            )
        else:
            # The normal time is still the iqamah (or the start), but at home.
            not_at_masjid[name] = (target, lines)

    # Pass 2: every other prayer. A moved one avoids the app's own events too.
    taken = [(e.starts_at, e.ends_at) for e in friday + [e for events in at_masjid.values() for e in events]]
    placed: dict[str, PlannedEvent] = {}
    for name in names:
        if name in at_masjid:
            continue
        couldnt_go = name in not_at_masjid
        if couldnt_go:
            normal, lines = not_at_masjid[name]
        else:
            normal, lines = _home_time(name, local_date, day, main, main_day, user_zone)
        length = PRAYER_LENGTHS[name]
        fit = fit_prayer(windows[name], normal, length, busy, taken, now) if windows else Fit("normal", normal, length)
        title = PRAYER_TITLES[name]
        if fit.kind == "normal" and not couldnt_go:
            # Just the prayer's name. Only masjid prayers say where.
            event = _home_event(setup, local_date, name, fit, lines + extra(name), lines[0], title, user_zone)
        elif fit.kind == "clash":
            why = f"Your event covers all of {title}'s time today, so there's no earlier or later time to pray it."
            event = _home_event(
                setup, local_date, name, fit, [why, *lines, _window_line(name, windows[name]), *extra(name)],
                lines[0], f"{title} (clash)", user_zone,
            )
        else:
            # Moved in time, or a masjid prayer prayed at home instead.
            moved = Fit("moved", fit.starts_at, fit.length)
            event = _home_event(
                setup, local_date, name, moved, [MOVED, *lines, _window_line(name, windows[name]), *extra(name)],
                lines[0], title, user_zone,
            )
        taken.append((event.starts_at, event.ends_at))
        placed[name] = event

    planned = list(friday)
    for name in names:
        planned.extend(at_masjid.get(name) or [placed[name]])
    return planned
