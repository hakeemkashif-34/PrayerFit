"""Saving fetched masjid times, and reading them back for the calendar."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.masjid_times.freshness import Freshness, freshness
from app.masjid_times.source import PRAYERS, DayTimes, get_source
from app.models import MasjidDayTimes, MasjidSource


def _values(day: DayTimes) -> dict:
    values: dict = {}
    for prayer in PRAYERS:
        values[f"{prayer}_adhan"] = day.adhan[prayer]
        values[f"{prayer}_iqamah"] = day.iqamah.get(prayer)
    values["jumuah"] = [slot.strftime("%H:%M") for slot in day.jumuah]
    return values


def _day(row: MasjidDayTimes) -> DayTimes:
    return DayTimes(
        local_date=row.local_date,
        adhan={p: getattr(row, f"{p}_adhan") for p in PRAYERS},
        iqamah={p: getattr(row, f"{p}_iqamah") for p in PRAYERS},
        jumuah=tuple(datetime.strptime(slot, "%H:%M").time() for slot in row.jumuah or []),
    )


def save_days(db: Session, masjid_id: uuid.UUID, source: str, days: list[DayTimes], now: datetime) -> bool:
    """Save every day. True if any of them is new or different. Doesn't commit."""
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
    changed = False
    for day in days:
        values = _values(day)
        changed = changed or saved.get(day.local_date) != values
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
