"""Pick the Jumuah for one Friday.

A pure function: it gets everything it needs as arguments and changes
nothing, so every case is easy to test.

Each slot has a window: from the leave time (the drive plus the Jumuah
"how early" minutes) to the end of the masjid's Jumuah. A slot fits when
its window doesn't overlap any busy time in the user's calendar.

The rule:
1. The user's pick (a masjid and a slot order), if its window fits.
2. If it clashes, or that slot isn't on this Friday, the earliest Jumuah
   that fits, across all their Jumuah masjids.
3. If every Jumuah clashes, the 1st Jumuah of the day (the earliest one),
   and say so.
4. No pick yet: the earliest Jumuah that fits.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.event_times import MasjidTrip, trip

# A masjid with no Jumuah length set (see admin.py set-jumuah-length) uses
# this, and its Jumuah event says the end time is estimated.
DEFAULT_JUMUAH_MINUTES = 45


@dataclass(frozen=True)
class JumuahSlot:
    masjid_id: uuid.UUID
    order: int  # 1, 2, or 3: MAWAQIT's jumua, jumua2, jumua3
    starts_at: datetime  # time zone aware


@dataclass(frozen=True)
class JumuahPick:
    masjid_id: uuid.UUID
    order: int


@dataclass(frozen=True)
class SlotWindow:
    slot: JumuahSlot
    trip: MasjidTrip
    ends_at: datetime
    fits: bool

    @property
    def starts_at(self) -> datetime:
        """When the window starts: leaving home, or arriving if the drive time is unknown."""
        return self.trip.leave_at or self.trip.arrive_at


@dataclass(frozen=True)
class JumuahChoice:
    window: SlotWindow | None  # None when there are no slots at all
    reason: str
    # "normal" when busy times didn't change the choice, "moved" when they
    # did, "clash" when every Jumuah clashes. Saved with the event.
    fit: str = "normal"


def ordinal(order: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(order, f"{order}th")


def _overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    return any(start < busy_end and busy_start < end for busy_start, busy_end in busy)


def slot_windows(
    slots: list[JumuahSlot],
    drive_seconds: dict[uuid.UUID, int | None],
    early_minutes: int,
    jumuah_minutes: dict[uuid.UUID, int],
    busy: list[tuple[datetime, datetime]],
) -> list[SlotWindow]:
    """Every slot's window and whether it fits, in the order given."""
    windows = []
    for slot in slots:
        planned = trip(slot.starts_at, early_minutes, drive_seconds.get(slot.masjid_id))
        length = timedelta(minutes=jumuah_minutes[slot.masjid_id])
        ends_at = (slot.starts_at.astimezone(UTC) + length).astimezone(slot.starts_at.tzinfo)
        start = planned.leave_at or planned.arrive_at
        windows.append(SlotWindow(slot, planned, ends_at, fits=not _overlaps(start, ends_at, busy)))
    return windows


def choose_jumuah(
    slots: list[JumuahSlot],
    pick: JumuahPick | None,
    drive_seconds: dict[uuid.UUID, int | None],
    early_minutes: int,
    jumuah_minutes: dict[uuid.UUID, int],
    busy: list[tuple[datetime, datetime]],
    listed_order: list[uuid.UUID],
) -> JumuahChoice:
    """The Jumuah for this Friday, and why it was chosen."""
    if not slots:
        return JumuahChoice(None, "None of your Jumuah masjids have Jumuah times.")

    def order_key(window: SlotWindow) -> tuple:
        listed = listed_order.index(window.slot.masjid_id) if window.slot.masjid_id in listed_order else len(listed_order)
        return (window.slot.starts_at, listed, window.slot.order)

    windows = sorted(slot_windows(slots, drive_seconds, early_minutes, jumuah_minutes, busy), key=order_key)
    fitting = [w for w in windows if w.fits]
    # A pick for a masjid that's no longer in their Jumuah list doesn't count.
    if pick is not None and pick.masjid_id not in listed_order:
        pick = None
    picked = next(
        (w for w in windows if pick and (w.slot.masjid_id, w.slot.order) == (pick.masjid_id, pick.order)), None
    )
    # What it would be on a free Friday, to tell whether busy times moved it.
    free_choice = picked or windows[0]

    if not fitting:
        return JumuahChoice(
            windows[0], "Every Jumuah clashes with your calendar, so this is the 1st Jumuah.", fit="clash"
        )

    def chose(window: SlotWindow, reason: str) -> JumuahChoice:
        return JumuahChoice(window, reason, fit="normal" if window is free_choice else "moved")

    if pick is None:
        return chose(fitting[0], "The earliest Jumuah that fits your calendar.")
    yours = f"Your pick ({ordinal(pick.order)} Jumuah)"
    if picked is not None and picked.fits:
        return chose(picked, f"{yours}.")
    why = "clashes with your calendar" if picked is not None else "isn't on this Friday"
    return chose(fitting[0], f"{yours} {why}, so this is the earliest Jumuah that fits.")
