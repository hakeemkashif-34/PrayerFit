"""Pick the Jumuah slot that fits the user's Friday.

A pure function: it gets everything it needs as arguments and changes
nothing, so it's easy to test every case.

The rule:
1. Drop every slot whose drive or prayer overlaps a busy time.
2. Pick the masjid with the shortest drive.
3. At that masjid, pick the earliest slot.
4. Masjids with an unknown drive time come after the known ones, in the
   order the user listed them.

Busy times stay empty until milestone 7 adds commitments, but the rule
already handles them.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.event_times import MasjidTrip, drive_minutes, trip

PRAYER_LENGTH = timedelta(minutes=15)


@dataclass(frozen=True)
class JumuahSlot:
    masjid_id: uuid.UUID
    starts_at: datetime  # time zone aware


@dataclass(frozen=True)
class JumuahChoice:
    slot: JumuahSlot | None
    trip: MasjidTrip | None
    reason: str


def _overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    return any(start < busy_end and busy_start < end for busy_start, busy_end in busy)


def pick_jumuah(
    slots: list[JumuahSlot],
    drive_seconds: dict[uuid.UUID, int | None],
    early_minutes: int,
    busy: list[tuple[datetime, datetime]],
    listed_order: list[uuid.UUID],
) -> JumuahChoice:
    """The chosen slot and why. slot is None when nothing fits."""
    if not slots:
        return JumuahChoice(None, None, "None of your Jumuah masjids have Jumuah times.")

    fitting = []
    for slot in slots:
        seconds = drive_seconds.get(slot.masjid_id)
        planned = trip(slot.starts_at, early_minutes, seconds)
        start = planned.leave_at or planned.arrive_at
        end = (slot.starts_at.astimezone(UTC) + PRAYER_LENGTH).astimezone(slot.starts_at.tzinfo)
        if not _overlaps(start, end, busy):
            fitting.append((slot, planned, seconds))
    if not fitting:
        return JumuahChoice(None, None, "Every Jumuah time clashes with something else on your Friday.")

    def order(item) -> tuple:
        slot, _, seconds = item
        listed = listed_order.index(slot.masjid_id) if slot.masjid_id in listed_order else len(listed_order)
        if seconds is None:
            return (1, 0, listed, slot.starts_at)
        return (0, seconds, listed, slot.starts_at)

    slot, planned, seconds = min(fitting, key=order)
    if seconds is None:
        reason = "Drive times aren't known, so this is the first masjid in your Jumuah list, at its earliest time."
    elif len({s.masjid_id for s, _, _ in fitting}) == 1:
        reason = f"Earliest Jumuah that fits, {drive_minutes(seconds)} min away."
    else:
        reason = f"Shortest drive of your Jumuah masjids ({drive_minutes(seconds)} min), at its earliest time."
    if len(fitting) < len(slots):
        reason += " Other times clash with your Friday."
    return JumuahChoice(slot, planned, reason)
