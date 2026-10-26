"""What the Jumuah chooser shows: each Jumuah slot (1st, 2nd, 3rd) at the user's Jumuah masjids.

The question is "Generally speaking, which Jumuah would you like to attend?",
so it isn't about one Friday and doesn't look at the user's calendar. This
week's times are only an example of when each slot is. The pick is saved
by order, and the weekly rule (jumuah.py) still checks it against the
user's calendar every Friday.

Read only: no Google, no OpenRouteService, nothing saved.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.event_plan import MasjidContext, jumuah_slots
from app.geo.timezones import masjid_time_zone
from app.jumuah import ordinal
from app.masjid_times.source import next_friday
from app.masjid_times.store import load_masjid_times
from app.models import Masjid
from app.prayer_times import DEFAULT_TIMEZONE
from app.user_settings import find_settings, jumuah_masjids, masjid_label


class SlotOut(BaseModel):
    masjid_id: uuid.UUID
    masjid_label: str
    order: int  # 1, 2, or 3
    order_label: str  # "1st Jumuah"
    # This week's times, as an example.
    starts_at: datetime
    ends_at: datetime
    jumuah_minutes: int
    # True when the masjid's Jumuah length isn't set, so it's 45 minutes.
    length_estimated: bool


class SlotKey(BaseModel):
    masjid_id: uuid.UUID
    order: int


class JumuahChoices(BaseModel):
    time_zone: str
    # Earliest first. Empty means the question is skipped.
    slots: list[SlotOut] = []
    # The saved pick if it's one of the slots, otherwise the 1st Jumuah.
    selected: SlotKey | None = None


def jumuah_choices(
    db: Session, user_id: uuid.UUID, now: datetime, masjids: list[Masjid] | None = None
) -> JumuahChoices:
    """masjids: the ones setup is about to save, before they're saved. None means the user's Jumuah masjids."""
    row = find_settings(db, user_id)
    zone = row.time_zone or DEFAULT_TIMEZONE
    if masjids is None:
        masjids = jumuah_masjids(db, user_id)
    if not masjids:
        return JumuahChoices(time_zone=zone)

    friday = next_friday(now.astimezone(ZoneInfo(zone)).date())
    times = load_masjid_times(db, [m.id for m in masjids], [friday], now)
    main_id = row.main_masjid_id if row.main_masjid_choice == "masjid" else None
    contexts = {
        m.id: MasjidContext(
            masjid=m,
            label=masjid_label(m, row.main_masjid_short_name if m.id == main_id else None),
            time_zone=masjid_time_zone(m),
            times=times.get(m.id),
            drive_seconds=None,
            jumuah_minutes=m.jumuah_minutes,
        )
        for m in masjids
    }
    listed = [m.id for m in masjids]
    slots = sorted(
        jumuah_slots(list(contexts.values()), friday),
        key=lambda s: (s.starts_at, listed.index(s.masjid_id), s.order),
    )
    if not slots:
        return JumuahChoices(time_zone=zone)

    keys = {(s.masjid_id, s.order) for s in slots}
    pick = (row.jumuah_pick_masjid_id, row.jumuah_pick_order)
    if pick in keys:
        selected = SlotKey(masjid_id=pick[0], order=pick[1])
    else:
        # The 1st Jumuah: the lowest slot at the first listed masjid that has any.
        first = min(slots, key=lambda s: (listed.index(s.masjid_id), s.order))
        selected = SlotKey(masjid_id=first.masjid_id, order=first.order)

    def slot_out(slot) -> SlotOut:
        context = contexts[slot.masjid_id]
        return SlotOut(
            masjid_id=slot.masjid_id,
            masjid_label=context.label,
            order=slot.order,
            order_label=f"{ordinal(slot.order)} Jumuah",
            starts_at=slot.starts_at,
            # Added in UTC, like every other event time.
            ends_at=(slot.starts_at.astimezone(UTC) + timedelta(minutes=context.jumuah_length)).astimezone(
                slot.starts_at.tzinfo
            ),
            jumuah_minutes=context.jumuah_length,
            length_estimated=context.jumuah_minutes is None,
        )

    return JumuahChoices(time_zone=zone, slots=[slot_out(s) for s in slots], selected=selected)

