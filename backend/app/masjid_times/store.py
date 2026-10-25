"""Saving fetched masjid times, and reading them back for the calendar."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.masjid_times.freshness import Freshness, freshness
from app.masjid_times.source import PRAYERS, DayTimes, JumuahTime, get_source
from app.models import MasjidDayTimes, MasjidSource


def _values(day: DayTimes) -> dict:
    values: dict = {}
    for prayer in PRAYERS:
        values[f"{prayer}_adhan"] = day.adhan[prayer]
        values[f"{prayer}_iqamah"] = day.iqamah.get(prayer)
    values["jumuah"] = [{"order": slot.order, "time": slot.time.strftime("%H:%M")} for slot in day.jumuah]
    return values


def _jumuah_time(saved, position: int) -> JumuahTime:
    """{"order": 2, "time": "14:00"}. Rows saved before slots had an order
    are just "14:00", numbered by position. The next read replaces them."""
    if isinstance(saved, str):
        return JumuahTime(position, datetime.strptime(saved, "%H:%M").time())
    return JumuahTime(int(saved["order"]), datetime.strptime(saved["time"], "%H:%M").time())


def _day(row: MasjidDayTimes) -> DayTimes:
    return DayTimes(
        local_date=row.local_date,
        adhan={p: getattr(row, f"{p}_adhan") for p in PRAYERS},
        iqamah={p: getattr(row, f"{p}_iqamah") for p in PRAYERS},
        jumuah=tuple(_jumuah_time(slot, n) for n, slot in enumerate(row.jumuah or [], start=1)),
    )


def save_days(db: Session, masjid_id: uuid.UUID, source: str, days: list[DayTimes], now: datetime) -> bool:
    """Save every day. Doesn't commit.

    True when a saved day's times changed, or on the first fetch. A new date
    at the far end isn't a change: each fetch adds one as the days go by,
    and counting it would rewrite every user's events daily.
    """
    dates = [d.local_date for d in days]
    saved = {
        row.local_date: _values(_day(row))
        for row in db.scalars(
            select(MasjidDayTimes).where(
                MasjidDayTimes.masjid_id == masjid_id,
                MasjidDayTimes.source == source,
                MasjidDayTimes.local_date.in_(dates),
            )
        )
    }
    first_fetch = not db.scalars(
        select(MasjidDayTimes.id).where(MasjidDayTimes.masjid_id == masjid_id, MasjidDayTimes.source == source).limit(1)
    ).first()
    changed = first_fetch
    for day in days:
        values = _values(day)
        if day.local_date in saved and saved[day.local_date] != values:
            changed = True
        db.execute(
            insert(MasjidDayTimes)
            .values(id=uuid.uuid4(), masjid_id=masjid_id, local_date=day.local_date, source=source, fetched_at=now, **values)
            .on_conflict_do_update(
                index_elements=["masjid_id", "local_date", "source"], set_={**values, "fetched_at": now}
            )
        )
    return changed


@dataclass(frozen=True)
class MasjidTimes:
    """One masjid's published times for the calendar window, and how old they are."""

    masjid_id: uuid.UUID
    source_label: str  # like "MAWAQIT"
    freshness: Freshness
    last_success_at: datetime | None
    # When a fetch last changed a time. Descriptions show this date.
    last_changed_at: datetime | None
    days: dict[date, DayTimes]

    def usable_day(self, local_date: date) -> DayTimes | None:
        """That day's times, or None if there are none or they're over 7 days old."""
        if not self.freshness.usable:
            return None
        return self.days.get(local_date)


def load_masjid_times(
    db: Session, masjid_ids: list[uuid.UUID], dates: list[date], now: datetime
) -> dict[uuid.UUID, MasjidTimes]:
    """Times for every linked masjid in masjid_ids. Masjids with no source are left out."""
    if not masjid_ids:
        return {}
    sources = db.scalars(select(MasjidSource).where(MasjidSource.masjid_id.in_(masjid_ids))).all()
    found = {}
    for source in sources:
        rows = db.scalars(
            select(MasjidDayTimes).where(
                MasjidDayTimes.masjid_id == source.masjid_id,
                MasjidDayTimes.source == source.source,
                MasjidDayTimes.local_date.in_(dates),
            )
        ).all()
        found[source.masjid_id] = MasjidTimes(
            masjid_id=source.masjid_id,
            source_label=get_source(source.source).label,
            freshness=freshness(source.last_success_at, now),
            last_success_at=source.last_success_at,
            last_changed_at=source.last_changed_at,
            days={row.local_date: _day(row) for row in rows},
        )
    return found
