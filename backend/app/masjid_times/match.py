"""Match a masjid on the map to my list of MAWAQIT masjids.

The rules:
1. Within 100 m, it's a match even if the names differ. A masjid's name on
   OpenStreetMap is often spelled differently from its MAWAQIT name, like
   "MAC QIC" against "Muslim Association of Canada", but 2 masjids are
   almost never within 100 m of each other.
2. From 100 m to 200 m, it's a match only if the names closely match.
   Coordinates can be off by a building or a parking lot, but this far out
   the name has to agree too.
3. A link is made only when exactly 1 listed masjid matches. 0 is "no
   match", and 2 or more is "unclear", so the app never guesses.

Plain functions, with no database and no network, so every rule is easy
to test.
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from app.geo.distance import distance_km

ANY_NAME_WITHIN_M = 100
SAME_NAME_WITHIN_M = 200
# How alike 2 names must be (0 to 1) when their words don't line up exactly.
CLOSE_NAME_RATIO = 0.85
# Words almost every masjid's name has, so they say nothing about which one it is.
COMMON_WORDS = {"masjid", "masjed", "mosque", "mosquee", "association", "centre", "center", "ottawa", "the", "of"}
NOT_A_LETTER = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Listed:
    """One masjid on the list."""

    external_id: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Candidate:
    entry: Listed
    distance_m: int


@dataclass(frozen=True)
class Match:
    # "linked", "no match", or "unclear"
    status: str
    candidates: tuple[Candidate, ...] = field(default=())

    @property
    def entry(self) -> Listed | None:
        return self.candidates[0].entry if self.status == "linked" else None

    @property
    def distance_m(self) -> int | None:
        return self.candidates[0].distance_m if self.status == "linked" else None


def name_words(name: str | None) -> list[str]:
    """ "Mosquée de Gatineau - CIO" -> ["de", "gatineau", "cio"]."""
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().casefold()
    return [word for word in NOT_A_LETTER.split(plain) if word and word not in COMMON_WORDS]


def names_match(a: str | None, b: str | None) -> bool:
    """True when 2 names are the same masjid's name, give or take common words and spelling.

    "Ottawa Main Mosque (OMA)" and "Ottawa Main Mosque" match: {main, oma}
    contains {main}. "Barrhaven Islamic Centre" and "Jami Omar" don't.
    """
    words_a, words_b = name_words(a), name_words(b)
    if not words_a or not words_b:
        return False
    set_a, set_b = set(words_a), set(words_b)
    if set_a <= set_b or set_b <= set_a:
        return True
    return difflib.SequenceMatcher(None, " ".join(words_a), " ".join(words_b)).ratio() >= CLOSE_NAME_RATIO


def match(latitude: float | None, longitude: float | None, name: str | None, listed: list[Listed]) -> Match:
    """Which listed masjid this one is, if exactly 1 fits."""
    if latitude is None or longitude is None:
        return Match("no match")
    candidates = []
    for entry in listed:
        metres = round(distance_km(latitude, longitude, entry.latitude, entry.longitude) * 1000)
        close = metres <= ANY_NAME_WITHIN_M
        same_name_nearby = metres <= SAME_NAME_WITHIN_M and names_match(name, entry.name)
        if close or same_name_nearby:
            candidates.append(Candidate(entry, metres))
    candidates.sort(key=lambda c: c.distance_m)
    if not candidates:
        return Match("no match")
    return Match("linked" if len(candidates) == 1 else "unclear", tuple(candidates))
