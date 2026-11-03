"""My list of masjids with published times, kept in app/data/mawaqit_masjids.csv.

Almost all are MAWAQIT pages. Masjid ar-Rahmah (AMA) isn't on MAWAQIT, so
its row links to its own website, https://www.mymasjid.ca/prayer/, and is
read by the mymasjid.ca adapter instead.

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
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.masjid_times.match import Listed
from app.masjid_times.mawaqit import BadLink, external_id_from_link
from app.masjid_times.mymasjid import EXTERNAL_ID as MYMASJID_ID
from app.masjid_times.mymasjid import PAGE_LINK
from app.models import MawaqitListEntry

MYMASJID_HOSTS = {"mymasjid.ca", "www.mymasjid.ca"}
LIST_FILE = Path(__file__).resolve().parent.parent / "data" / "mawaqit_masjids.csv"
# times_link is the masjid's MAWAQIT link, or https://www.mymasjid.ca/prayer/ for Masjid ar-Rahmah.
COLUMNS = ["name", "short_name", "address", "times_link", "latitude", "longitude"]


class BadListRow(ValueError):
    """A line in the file isn't valid. The message says which line."""


@dataclass(frozen=True)
class ListRow:
    external_id: str
    name: str
    latitude: float
    longitude: float
    # Both optional. Setup's search uses them.
    short_name: str | None = None
    address: str | None = None
    source: str = "mawaqit"


def source_from_link(link: str) -> tuple[str, str]:
    """A list link -> (source, saved ID).

    "https://mawaqit.net/en/id/9793" -> ("mawaqit", "id/9793")
    "https://www.mymasjid.ca/prayer/" -> ("mymasjid", "mymasjid.ca")
    Only that exact mymasjid.ca page is accepted. The adapter reads its own
    fixed URL, so nothing from the link is used except which source it is.
    """
    parts = urlsplit(link.strip())
    if (parts.hostname or "").lower() in MYMASJID_HOSTS:
        if parts.scheme != "https" or parts.port or parts.username or parts.path.rstrip("/") != "/prayer":
            raise BadLink(f"The only mymasjid.ca link accepted is {PAGE_LINK}")
        return "mymasjid", MYMASJID_ID
    return "mawaqit", external_id_from_link(link)


def _optional(text: str | None) -> str | None:
    return " ".join((text or "").split()) or None


def check_row(
    name: str,
    link: str,
    latitude: str | float,
    longitude: str | float,
    short_name: str | None = None,
    address: str | None = None,
) -> ListRow:
    """One masjid's details, checked. Raises BadLink or ValueError with a short reason."""
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("the name is empty")
    source, external_id = source_from_link(link)
    lat, lon = float(latitude), float(longitude)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("latitude must be from -90 to 90 and longitude from -180 to 180")
    return ListRow(external_id, name, lat, lon, _optional(short_name), _optional(address), source)


def read_file(path: Path = LIST_FILE) -> list[ListRow]:
    """Every row in the file. One bad line stops the load, so a typo can't link the wrong masjid."""
    rows: dict[str, ListRow] = {}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, skipinitialspace=True)
        if reader.fieldnames != COLUMNS:
            raise BadListRow(f"{path.name} must start with the line: {','.join(COLUMNS)}")
        for line, raw in enumerate(reader, start=2):
            try:
                row = check_row(
                    raw["name"], raw["times_link"], raw["latitude"], raw["longitude"], raw["short_name"], raw["address"]
                )
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
        values = {
            "name": row.name, "short_name": row.short_name, "address": row.address,
            "latitude": row.latitude, "longitude": row.longitude, "source": row.source,
        }
        saved = db.execute(
            insert(MawaqitListEntry)
            .values(external_id=row.external_id, added_by=added_by, added_at=now, **values)
            .on_conflict_do_update(
                index_elements=["external_id"],
                set_=values,
                # Only when something is different, so an unchanged row counts as 0.
                where=or_(
                    MawaqitListEntry.name.is_distinct_from(row.name),
                    MawaqitListEntry.short_name.is_distinct_from(row.short_name),
                    MawaqitListEntry.address.is_distinct_from(row.address),
                    MawaqitListEntry.latitude.is_distinct_from(row.latitude),
                    MawaqitListEntry.longitude.is_distinct_from(row.longitude),
                    MawaqitListEntry.source.is_distinct_from(row.source),
                ),
            )
            .returning(MawaqitListEntry.external_id)
        ).first()
        changed += saved is not None
    return changed


def listed(db: Session) -> list[Listed]:
    return [
        Listed(e.external_id, e.name, e.latitude, e.longitude, e.short_name, e.address, e.source)
        for e in db.scalars(select(MawaqitListEntry).order_by(MawaqitListEntry.name))
    ]
