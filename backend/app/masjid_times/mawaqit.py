"""Read a masjid's times from its public MAWAQIT page.

A MAWAQIT page has the masjid's whole year built into it as data, in a
script that starts "confData = {". This adapter:
1. Downloads the page, with a timeout and a 3 MB limit.
2. Finds confData and reads it as JSON. Nothing on the page is ever run.
3. Turns the yearly tables into one row per local date, and checks them.

What confData holds (only these parts are used):
- calendar: 12 months. Each maps a day ("1" to "31") to 6 times:
  Fajr, sunrise, Dhuhr, Asr, Maghrib, Isha.
- iqamaCalendar: 12 months. Each maps a day to 5 iqamah values, either a
  clock time ("20:15") or minutes after adhan ("+10").
- jumua, jumua2, jumua3: Friday prayer times, empty when not used.
- jumuaAsDuhr: true when Jumuah is at Dhuhr time instead of set times.
- iqamaEnabled: false when the masjid publishes no iqamah times.
- fajrFixationComparedToShuruq: a Fajr setting tied to sunrise. Its
  format isn't known (KMA leaves it empty), so when it's set, Fajr's
  iqamah is treated as not available instead of guessed.

"+0" in iqamaCalendar is iqamah at the adhan time (see validate.py).

MAWAQIT can block this at any time. When it does, the app keeps the last
good times for up to 7 days, then falls back to calculated times.
"""

import json
import logging
import re
import time as clock
from datetime import date, time, timedelta
from urllib.parse import urljoin, urlsplit

import httpx2

from app.config import get_osm_settings
from app.http_client import log_failure, transport_reason
from app.masjid_times.source import (
    PRAYERS,
    DayTimes,
    JumuahTime,
    SourceBlocked,
    SourceFailed,
    SourceInvalid,
    next_friday,
)
from app.masjid_times.validate import check_day, clock_time, iqamah_time

logger = logging.getLogger("app.masjid_times")

MAX_PAGE_BYTES = 3 * 1024 * 1024
TIMEOUT_SECONDS = 10
HOSTS = {"mawaqit.net", "www.mawaqit.net"}
# Fixed here, not read from settings, so pages only ever come from MAWAQIT.
BASE_URL = "https://mawaqit.net"
# MAWAQIT page names are lowercase words joined by hyphens, like "kma-kanata".
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# A share link's masjid ID, saved as "id/9793". Share links look like mawaqit.net/en/id/9793.
ID_EXTERNAL = re.compile(r"^id/([0-9]{1,12})$")
# MAWAQIT answers a share link with the page itself. If that ever turns into
# a redirect, a few hops within mawaqit.net are followed, and nothing else.
MAX_REDIRECTS = 3
# Path parts that can come before the page name: a language, and "m" or "w"
# for the mobile and widget versions of the same page.
LANGUAGE = re.compile(r"^[a-z]{2}$")
VIEW_PREFIXES = {"m", "w"}
CONF_DATA = re.compile(r"\bconfData\s*=\s*")


class BadLink(ValueError):
    """The link isn't a MAWAQIT masjid page."""


def _mawaqit_path(link: str, strip_language: bool = True) -> list[str]:
    """The parts of an https://mawaqit.net link's path, without the language. Anything else is a BadLink."""
    parts = urlsplit(link.strip())
    if parts.scheme != "https" or (parts.hostname or "").lower() not in HOSTS:
        raise BadLink("Only https://mawaqit.net links are accepted.")
    if parts.port is not None or parts.username or parts.password:
        raise BadLink("Only https://mawaqit.net links are accepted.")
    path = [p for p in parts.path.split("/") if p]
    if strip_language and path and LANGUAGE.match(path[0]):
        path = path[1:]
    return path


def slug_from_link(link: str) -> str:
    """"https://mawaqit.net/en/kma-kanata" -> "kma-kanata".

    Only https links on mawaqit.net are accepted, and only the page name is
    kept. The app builds the URL from it again, so nothing else from the
    link is ever used.
    """
    path = _mawaqit_path(link)
    if path and path[0] in VIEW_PREFIXES:
        path = path[1:]
    if len(path) != 1 or not SLUG.match(path[0].lower()):
        raise BadLink("That link isn't a MAWAQIT masjid page, like https://mawaqit.net/en/your-masjid.")
    return path[0].lower()


def external_id_from_link(link: str) -> str:
    """A share link gives "id/9793". A page link gives its name, like "cio-gatineau".

    "https://mawaqit.net/en/id/9793" -> "id/9793"
    "https://mawaqit.net/en/cio-gatineau" -> "cio-gatineau"
    """
    raw = _mawaqit_path(link, strip_language=False)
    # "id" is also a language code (Indonesian), so try the path with and without a language in front.
    paths = [raw, raw[1:] if raw and LANGUAGE.match(raw[0]) else []]
    for path in paths:
        if len(path) == 2 and path[0] == "id" and ID_EXTERNAL.match(f"id/{path[1]}"):
            return f"id/{path[1]}"
    # Like "/en/id/abc": a share link with a typo, not a page.
    if paths[1][:1] == ["id"] or (len(raw) == 1 and raw[0] == "id"):
        raise BadLink("A MAWAQIT share link ends in a number, like https://mawaqit.net/en/id/9793.")
    slug = slug_from_link(link)
    if slug == "id":
        raise BadLink("A MAWAQIT share link ends in a number, like https://mawaqit.net/en/id/9793.")
    return slug


def page_url(external_id: str) -> str:
    """The URL for a saved ID. It's always built here, so a saved value can't point anywhere else."""
    found = ID_EXTERNAL.match(external_id)
    if found:
        return f"{BASE_URL}/en/id/{found.group(1)}"
    if not SLUG.match(external_id):
        raise BadLink("Saved MAWAQIT ID isn't valid.")
    return f"{BASE_URL}/en/{external_id}"


def _redirect_target(url: str, location: str | None) -> str:
    """Where a redirect goes, only if it stays on https://mawaqit.net."""
    target = urlsplit(urljoin(url, location or ""))
    if (
        target.scheme != "https"
        or (target.hostname or "").lower() not in HOSTS
        or target.port is not None
        or target.username
        or target.password
    ):
        raise SourceFailed("MAWAQIT redirected to another site")
    return target.geturl()


def download(http: httpx2.Client, external_id: str) -> str:
    """The page's HTML. Raises SourceBlocked or SourceFailed."""
    started = clock.monotonic()
    url = page_url(external_id)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            with http.stream(
                "GET",
                url,
                headers={"User-Agent": get_osm_settings().user_agent},
                timeout=TIMEOUT_SECONDS,
                # Followed by hand below, so each hop is checked first.
                follow_redirects=False,
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = _redirect_target(url, response.headers.get("location"))
                    continue
                if response.status_code in (403, 429):
                    log_failure("MAWAQIT", f"status {response.status_code}", started)
                    raise SourceBlocked(f"MAWAQIT answered {response.status_code}")
                if response.status_code != 200:
                    log_failure("MAWAQIT", f"status {response.status_code}", started)
                    raise SourceFailed(f"MAWAQIT answered {response.status_code}")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_PAGE_BYTES:
                        log_failure("MAWAQIT", "page too big", started)
                        raise SourceFailed("MAWAQIT page is bigger than 3 MB")
                return body.decode("utf-8", errors="replace")
    except httpx2.TransportError as error:
        reason = transport_reason(error)
        log_failure("MAWAQIT", reason, started)
        raise SourceFailed(f"Couldn't reach MAWAQIT: {reason}") from error
    log_failure("MAWAQIT", "too many redirects", started)
    raise SourceFailed(f"MAWAQIT redirected more than {MAX_REDIRECTS} times")


def conf_data(html: str) -> dict:
    """The confData object, read as JSON. Never run as code."""
    match = CONF_DATA.search(html)
    if match is None:
        raise SourceInvalid("MAWAQIT page has no confData")
    try:
        data, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError as error:
        raise SourceInvalid("MAWAQIT confData isn't JSON") from error
    if not isinstance(data, dict):
        raise SourceInvalid("MAWAQIT confData isn't an object")
    return data


def _month_table(data: dict, key: str, month: int) -> dict:
    table = data.get(key)
    if not isinstance(table, list) or len(table) != 12 or not isinstance(table[month - 1], dict):
        raise SourceInvalid(f"MAWAQIT {key} doesn't have 12 months")
    return table[month - 1]


def jumuah_slots(data: dict) -> tuple[JumuahTime, ...]:
    """jumua is the 1st Jumuah, jumua2 the 2nd, and jumua3 the 3rd. An empty one is skipped,
    but the others keep their number, so a pick of "3rd Jumuah" still means jumua3."""
    if data.get("jumuaAsDuhr") is True:
        # No set Jumuah times on the page, so none are made up.
        return ()
    slots = []
    for order, key in enumerate(("jumua", "jumua2", "jumua3"), start=1):
        value = data.get(key)
        if value in (None, ""):
            continue
        slots.append(JumuahTime(order, clock_time(value, f"MAWAQIT {key}")))
    return tuple(slots)


def fajr_tied_to_sunrise(data: dict) -> bool:
    """True when the page sets fajrFixationComparedToShuruq.

    It could change Fajr's iqamah in a way the iqamah table doesn't show,
    so Fajr's iqamah isn't used. Empty, null, and false mean it's off.
    """
    value = data.get("fajrFixationComparedToShuruq")
    # "is False", not "in (..., False)": 0 == False in Python, and 0 is a real setting.
    return not (value is None or value is False or value == "")


def days_from(data: dict, today: date, days: int) -> list[DayTimes]:
    """One DayTimes per local date, from today. Each date is today plus n
    days, so a daylight saving change can't skip or repeat one."""
    iqamah_published = data.get("iqamaEnabled", True) is not False
    skip_fajr_iqamah = fajr_tied_to_sunrise(data)
    slots = jumuah_slots(data)
    found = []
    for n in range(days):
        local_date = today + timedelta(days=n)
        times = _month_table(data, "calendar", local_date.month).get(str(local_date.day))
        if not isinstance(times, list) or len(times) != 6:
            raise SourceInvalid(f"MAWAQIT has no times for {local_date}")
        # Index 1 is sunrise, which isn't a prayer.
        adhan = {
            prayer: clock_time(times[index], f"{local_date} {prayer} adhan")
            for prayer, index in zip(PRAYERS, (0, 2, 3, 4, 5))
        }
        iqamah: dict[str, time | None] = dict.fromkeys(PRAYERS)
        if iqamah_published:
            values = _month_table(data, "iqamaCalendar", local_date.month).get(str(local_date.day))
            if isinstance(values, list) and len(values) == 5:
                iqamah = {
                    prayer: iqamah_time(value, adhan[prayer], f"{local_date} {prayer} iqamah")
                    for prayer, value in zip(PRAYERS, values)
                }
            elif values is not None:
                raise SourceInvalid(f"MAWAQIT iqamah for {local_date} isn't 5 values")
        if skip_fajr_iqamah:
            iqamah["fajr"] = None
        day = DayTimes(
            local_date=local_date,
            adhan=adhan,
            iqamah=iqamah,
            # MAWAQIT only holds this week's Jumuah times.
            jumuah=slots if local_date == next_friday(today) else (),
        )
        check_day(day)
        found.append(day)
    return found


class MawaqitSource:
    name = "mawaqit"
    label = "MAWAQIT"

    def fetch(self, http: httpx2.Client, external_id: str, today: date, days: int) -> list[DayTimes]:
        data = conf_data(download(http, external_id))
        if fajr_tied_to_sunrise(data):
            # The page name is public, so it's safe to log. Nothing about any user is.
            logger.warning(
                "MAWAQIT page %s sets fajrFixationComparedToShuruq, so its Fajr iqamah isn't used", external_id
            )
        return days_from(data, today, days)
