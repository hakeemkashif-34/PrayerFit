"""My list of MAWAQIT masjids, kept in app/data/mawaqit_masjids.csv.

MAWAQIT's search needs a login and it has no sitemap, so the app can't
find a masjid's page by itself. I collect them by hand, with the link and
where the masjid is. The app loads the file every time it starts:
1. Each row is saved by its MAWAQIT ID, so loading it again never adds a copy.
2. A name or location I fix in the file replaces the saved one.
3. A row I remove from the file stays saved. Removing a masjid is rare, and
   users may already be linked to it.

Adding a masjid is a new line in the file, not a migration. The admin
command add-mawaqit adds one straight away too.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.masjid_times.match import Listed
from app.masjid_times.mawaqit import BadLink, external_id_from_link
from app.models import MawaqitListEntry

LIST_FILE = Path(__file__).resolve().parent.parent / "data" / "mawaqit_masjids.csv"
COLUMNS = ["name", "mawaqit_link", "latitude", "longitude"]


class BadListRow(ValueError):
    """A line in the file isn't valid. The message says which line."""


@dataclass(frozen=True)
class ListRow:
    external_id: str
    name: str
    latitude: float
    longitude: float


def check_row(name: str, link: str, latitude: str | float, longitude: str | float) -> ListRow:
    """One masjid's details, checked. Raises BadLink or ValueError with a short reason."""
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("the name is empty")
    external_id = external_id_from_link(link)
    lat, lon = float(latitude), float(longitude)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("latitude must be from -90 to 90 and longitude from -180 to 180")
    return ListRow(external_id, name, lat, lon)


def read_file(path: Path = LIST_FILE) -> list[ListRow]:
    """Every row in the file. One bad line stops the load, so a typo can't link the wrong masjid."""
    rows: dict[str, ListRow] = {}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, skipinitialspace=True)
        if reader.fieldnames != COLUMNS:
            raise BadListRow(f"{path.name} must start with the line: {','.join(COLUMNS)}")
        for line, raw in enumerate(reader, start=2):
            try:
                row = check_row(raw["name"], raw["mawaqit_link"], raw["latitude"], raw["longitude"])
            except (BadLink, ValueError, TypeError) as error:
                raise BadListRow(f"{path.name} line {line}: {error}") from error
            if row.external_id in rows:
                raise BadListRow(f"{path.name} line {line}: {row.external_id} is already in the file")
            rows[row.external_id] = row
    return list(rows.values())


def save_rows(db: Session, rows: list[ListRow], added_by: str, now: datetime) -> int:
    """Add new rows and update changed ones. Returns how many were added or changed."""
    changed = 0
    for row in rows:
        values = {"name": row.name, "latitude": row.latitude, "longitude": row.longitude}
        saved = db.execute(
            insert(MawaqitListEntry)
            .values(external_id=row.external_id, added_by=added_by, added_at=now, **values)
            .on_conflict_do_update(
                index_elements=["external_id"],
                set_=values,
                # Only when something is different, so an unchanged row counts as 0.
                where=or_(
                    MawaqitListEntry.name.is_distinct_from(row.name),
                    MawaqitListEntry.latitude.is_distinct_from(row.latitude),
                    MawaqitListEntry.longitude.is_distinct_from(row.longitude),
                ),
            )
            .returning(MawaqitListEntry.external_id)
        ).first()
        changed += saved is not None
    return changed


def listed(db: Session) -> list[Listed]:
    return [
        Listed(e.external_id, e.name, e.latitude, e.longitude)
        for e in db.scalars(select(MawaqitListEntry).order_by(MawaqitListEntry.name))
    ]
