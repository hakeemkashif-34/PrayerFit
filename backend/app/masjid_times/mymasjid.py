"""Read Masjid ar-Rahmah's (AMA, Ottawa) times from its own website.

The masjid isn't on MAWAQIT. Its prayer page (https://www.mymasjid.ca/prayer/)
shows an "Iqaama Timetable" in an iframe, and the iframe is a small table
served by https://app.mymasjid.ca/protected/public/timetable:

    Salāh    | Adhān    | Iqāmah   | (Arabic name)
    Fajr     | 05:22 AM | 05:52 AM | الفجر
    Zuhr     | 11:46 AM | 12:30 PM | الظهر
    ...
    Jumuʿah  | 12:00 PM |          | الجمعة
    Jumuʿah 2| 01:30 PM |          | الجمعة

What the table means, and how it's read:
1. It's today only. There's no date on it and no way to ask for another day,
   so the app saves it as the masjid's local date at the time of the read.
   Days that haven't been read use calculated times (never a copy of today).
2. "Zuhr" is Dhuhr.
3. An empty Iqāmah cell means the masjid didn't publish one. It stays empty
   and the calculated time is used. An iqamah is never made up.
4. Jumuah rows only have a time in the Adhān column. That's the Jumuah start
   time, and no iqamah is claimed for it. They're saved for the coming Friday.
5. The HTML is only read as text. Nothing on the page is ever run.

The site can change or go down at any time. Then the last good day's times
stay saved, the Settings notice shows after 24 hours, and every day that
wasn't read uses calculated times.
"""

import logging
import re
import time as clock
import unicodedata
from datetime import date, time
from html.parser import HTMLParser

import httpx2

from app.config import get_osm_settings
from app.http_client import log_failure, transport_reason
from app.masjid_times.mawaqit import status_text
from app.masjid_times.source import (
    PRAYERS,
    DayTimes,
    FetchedDays,
    JumuahTime,
    SkippedDay,
    SourceBlocked,
    SourceFailed,
    SourceInvalid,
    UpcomingJumuah,
    next_friday,
)
from app.masjid_times.validate import check_day

logger = logging.getLogger("app.masjid_times")

# Fixed here, never built from saved data, so reads only ever go to this page.
URL = "https://app.mymasjid.ca/protected/public/timetable"
# Saved in masjid_sources.external_id and the masjid list. There's only one masjid on this site.
EXTERNAL_ID = "mymasjid.ca"
# The masjid's own page that links people to the table. My masjid list uses it.
PAGE_LINK = "https://www.mymasjid.ca/prayer/"
# The real table is about 1.5 KB.
MAX_PAGE_BYTES = 256 * 1024
TIMEOUT_SECONDS = 10
# Names in the first column, with accents and spaces removed and lowercased.
PRAYER_NAMES = {"fajr": "fajr", "zuhr": "dhuhr", "dhuhr": "dhuhr", "asr": "asr", "maghrib": "maghrib", "isha": "isha"}
JUMUAH_NAMES = {"jumuah": 1, "jumuah1": 1, "jumuah2": 2, "jumuah3": 3}
# 12-hour clock, like "05:22 AM" or "1:30 pm".
TWELVE_HOUR = re.compile(r"^(1[0-2]|0?[1-9]):([0-5]\d)\s*([AaPp][Mm])$")


class _Table(HTMLParser):
    """Collects the text of every <td> in every <tr>. Script and style text is skipped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def name_key(text: str) -> str:
    """"Jumuʿah 2" -> "jumuah2", "Zuhr" -> "zuhr". Accents and marks are dropped."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain.lower() if c.isascii() and c.isalnum())


def twelve_hour(value: str, what: str) -> time:
    """"05:22 AM" -> 5:22, "12:30 PM" -> 12:30, "12:15 AM" -> 0:15. Anything else fails."""
    found = TWELVE_HOUR.match(value.strip())
    if found is None:
        raise SourceInvalid(f"{what} isn't a clock time")
    hour, minute, half = int(found.group(1)), int(found.group(2)), found.group(3).upper()
    if half == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return time(hour, minute)


def table_rows(html: str) -> list[list[str]]:
    parser = _Table()
    parser.feed(html)
    parser.close()
    return [row for row in parser.rows if row]


def read_table(html: str, today: date) -> FetchedDays:
    """Today's times and the coming Friday's Jumuah, from the table's HTML.

    A missing prayer, a repeated one, or a bad time rejects the read, since
    there's only one day on the page. A bad Jumuah time only skips Jumuah.
    """
    adhan: dict[str, time] = {}
    iqamah: dict[str, time | None] = {}
    jumuah: dict[int, str] = {}
    for row in table_rows(html):
        key = name_key(row[0])
        if key in PRAYER_NAMES:
            prayer = PRAYER_NAMES[key]
            if prayer in adhan:
                raise SourceInvalid(f"mymasjid.ca lists {prayer} twice")
            if len(row) < 3:
                raise SourceInvalid(f"{today} {prayer} row doesn't have an adhan and an iqamah column")
            adhan[prayer] = twelve_hour(row[1], f"{today} {prayer} adhan")
            # Empty means not published. It stays empty.
            iqamah[prayer] = twelve_hour(row[2], f"{today} {prayer} iqamah") if row[2] else None
        elif key in JUMUAH_NAMES and len(row) >= 2 and row[1]:
            jumuah[JUMUAH_NAMES[key]] = row[1]
        # The header row and anything new on the page are skipped.
    missing = [p for p in PRAYERS if p not in adhan]
    if missing:
        raise SourceInvalid(f"mymasjid.ca has no {', '.join(missing)} time for {today}")

    day = DayTimes(local_date=today, adhan=adhan, iqamah=iqamah)
    # The only day on the page, so a failed check rejects the read. The reason names the date and the prayer.
    check_day(day)

    friday = next_friday(today)
    skipped: list[SkippedDay] = []
    try:
        slots = tuple(
            JumuahTime(order, twelve_hour(value, f"{friday} Jumuah {order}")) for order, value in sorted(jumuah.items())
        )
        upcoming: UpcomingJumuah | None = UpcomingJumuah(friday, slots)
    except SourceInvalid as error:
        # The 5 prayers are still good. Jumuah keeps its last good times.
        skipped.append(SkippedDay(friday, str(error)))
        upcoming = None
    return FetchedDays([day], skipped, upcoming)


def download(http: httpx2.Client) -> str:
    """The table's HTML. Raises SourceBlocked or SourceFailed. Redirects aren't followed."""
    started = clock.monotonic()
    service = "mymasjid.ca timetable"
    try:
        with http.stream(
            "GET",
            URL,
            headers={"User-Agent": get_osm_settings().user_agent},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            if response.status_code in (403, 429):
                log_failure(service, status_text(response), started)
                raise SourceBlocked(f"mymasjid.ca answered {status_text(response)}")
            if response.status_code != 200:
                # A redirect too: the table moving somewhere else needs a look by hand.
                log_failure(service, status_text(response), started)
                raise SourceFailed(f"mymasjid.ca answered {status_text(response)}")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_PAGE_BYTES:
                    log_failure(service, "page too big", started)
                    raise SourceFailed("mymasjid.ca page is bigger than 256 KB")
            return body.decode("utf-8", errors="replace")
    except httpx2.TransportError as error:
        reason = transport_reason(error)
        log_failure(service, reason, started)
        raise SourceFailed(f"Couldn't reach mymasjid.ca: {reason}") from error


class MyMasjidSource:
    name = "mymasjid"
    # Shown in Settings and saved with each event, like "Masjid ar-Rahmah iqamah (mymasjid.ca, updated ...)".
    label = "mymasjid.ca"
    # Only today is on the page, so days that weren't read use calculated times.
    keeps_future_days = False

    def fetch(self, http: httpx2.Client, external_id: str, today: date, days: int) -> FetchedDays:
        if external_id != EXTERNAL_ID:
            raise SourceFailed("Saved mymasjid.ca ID isn't valid")
        fetched = read_table(download(http), today)
        for prayer, value in fetched.days[0].iqamah.items():
            if value is None:
                logger.info("mymasjid.ca has no %s iqamah for %s, so the calculated time is used", prayer, today)
        for skipped in fetched.skipped:
            logger.warning("mymasjid.ca: skipped Jumuah: %s", skipped.reason)
        return fetched
