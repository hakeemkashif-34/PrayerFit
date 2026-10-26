"""What the Jumuah chooser shows: this Friday's slots, busy times, and which slot fits.

The chooser is on the optional setup page and the Settings page. Each slot
shows its full window, from leaving home to the end of Jumuah. The same
picker as the calendar update decides which slot is selected.
"""

import uuid
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.busy_times import busy_on
from app.calendar_window import masjid_inputs
from app.event_plan import jumuah_slots
from app.event_times import drive_minutes
from app.jumuah import choose_jumuah, ordinal, slot_windows
from app.masjid_times.source import next_friday
from app.user_settings import load_setup


class BusyOut(BaseModel):
    starts_at: datetime
    ends_at: datetime


class SlotOut(BaseModel):
    masjid_id: uuid.UUID
    masjid_label: str
    order: int  # 1, 2, or 3
    order_label: str  # "1st Jumuah"
    starts_at: datetime
    # Null when the drive time is unknown, so there's no drive block.
    leave_at: datetime | None
    arrive_at: datetime
    ends_at: datetime
    drive_minutes: int | None
    jumuah_minutes: int
    # True when the masjid's Jumuah length isn't set, so it's 45 minutes.
    length_estimated: bool
    # False when the window overlaps a busy time. It can still be picked.
    fits: bool


class SlotKey(BaseModel):
    masjid_id: uuid.UUID
    order: int


class JumuahChoices(BaseModel):
    # The coming Friday (today, if it's Friday). Null when there's nothing to choose from.
    friday: date | None = None
    time_zone: str | None = None
    # False when busy times couldn't be checked (no access yet, or Google failed).
    busy_checked: bool = False
    busy: list[BusyOut] = []
    # Earliest first. Empty means the chooser is skipped.
    slots: list[SlotOut] = []
    # The user's pick if it's on this Friday, otherwise the earliest that fits.
    selected: SlotKey | None = None


def jumuah_choices(
    db: Session,
    http: httpx2.Client,
    user_id: uuid.UUID,
    now: datetime,
    early_override: int | None = None,
) -> JumuahChoices:
    setup = load_setup(db, user_id, finished=False)
    if setup is None or not setup.jumuah_masjids:
        return JumuahChoices()
    if early_override is not None:
        setup = replace(setup, jumuah_arrive_early_minutes=early_override)
    friday = next_friday(now.astimezone(ZoneInfo(setup.time_zone)).date())
    inputs = masjid_inputs(db, http, setup, [friday], now)
    slots = jumuah_slots(inputs.jumuah, friday)
    if not slots:
        return JumuahChoices(friday=friday, time_zone=setup.time_zone)

    busy = busy_on(db, http, user_id, friday, setup.time_zone)
    by_id = {c.masjid.id: c for c in inputs.jumuah}
    windows = sorted(
        slot_windows(
            slots,
            {c.masjid.id: c.drive_seconds for c in inputs.jumuah},
            setup.jumuah_arrive_early_minutes,
            {c.masjid.id: c.jumuah_length for c in inputs.jumuah},
            busy.busy,
        ),
        key=lambda w: (w.slot.starts_at, w.slot.order),
    )
    listed = [c.masjid.id for c in inputs.jumuah]
    pick = setup.jumuah_pick
    picked = pick is not None and any((w.slot.masjid_id, w.slot.order) == (pick.masjid_id, pick.order) for w in windows)
    if picked:
        selected = SlotKey(masjid_id=pick.masjid_id, order=pick.order)
    else:
        # No pick on this Friday: the earliest that fits, the same as the calendar would use.
        choice = choose_jumuah(
            slots, None, {c.masjid.id: c.drive_seconds for c in inputs.jumuah}, setup.jumuah_arrive_early_minutes,
            {c.masjid.id: c.jumuah_length for c in inputs.jumuah}, busy.busy, listed,
        )
        selected = SlotKey(masjid_id=choice.window.slot.masjid_id, order=choice.window.slot.order)

    def slot_out(window) -> SlotOut:
        context = by_id[window.slot.masjid_id]
        return SlotOut(
            masjid_id=context.masjid.id,
            masjid_label=context.label,
            order=window.slot.order,
            order_label=f"{ordinal(window.slot.order)} Jumuah",
            starts_at=window.slot.starts_at,
            leave_at=window.trip.leave_at,
            arrive_at=window.trip.arrive_at,
            ends_at=window.ends_at,
            drive_minutes=drive_minutes(context.drive_seconds) if context.drive_seconds is not None else None,
            jumuah_minutes=context.jumuah_length,
            length_estimated=context.jumuah_minutes is None,
            fits=window.fits,
        )

    return JumuahChoices(
        friday=friday,
        time_zone=setup.time_zone,
        busy_checked=busy.checked,
        busy=[BusyOut(starts_at=start, ends_at=end) for start, end in busy.busy],
        slots=[slot_out(w) for w in windows],
        selected=selected,
    )
