"""Setup's masjid search: my own MAWAQIT list first, then Photon.

Why the list comes first: a user typed "Barrhaven Islamic Centre" and it
didn't show up. Photon only finds what OpenStreetMap has, under the name
and tags it has there, and it doesn't forgive spelling mistakes well. My
list has the name I chose, a short name, and a working MAWAQIT link, so a
masjid on it should always be found.

The order:
1. List masjids that match what was typed, best match first, then nearest.
   Distance doesn't matter for these, since I picked every one by hand.
2. Photon's results (see geo/photon.py), minus any that are the same
   masjid as a list one already shown (same rules as auto-linking, see
   masjid_times/match.py).
At most 5 in total.

Matching is forgiving, word by word, ignoring words like "masjid" and
"centre". Each word typed has to match a word of the name or the short name:
1. The same word, or the start of one: "barr" finds "barrhaven".
2. Close enough with a small typo: "barhaven" finds "barrhaven".
So "barrhaven", "BIC", and "barhaven islamic" all find Barrhaven Islamic Centre.

The list is public (my own CSV), so nothing about the user is used except
the home location, to sort by distance.
"""

import difflib
from datetime import datetime

import httpx2
from sqlalchemy.orm import Session

from app.geo.distance import distance_km
from app.geo.errors import OsmServiceError
from app.geo.photon import MAX_SUGGESTIONS, MIN_QUERY_LENGTH, Suggestion, normalize, suggest_masjids
from app.masjid_times.match import Listed, match, name_words
from app.masjid_times.mawaqit_list import listed

# How alike a typed word and a name word must be (0 to 1) to count as a typo.
TYPO_RATIO = 0.8
# Shorter words have to match exactly or as the start of a word. "bi" is too short to guess at.
TYPO_MIN_LENGTH = 4


def word_score(typed: str, word: str) -> float:
    """How well one typed word matches one word of a name. 0 is no match."""
    if typed == word:
        return 1.0
    if word.startswith(typed):
        return 0.9
    if len(typed) < TYPO_MIN_LENGTH:
        return 0.0
    # The whole word, or the start of it, for a typo in a partial name like "barhav".
    ratio = max(
        difflib.SequenceMatcher(None, typed, word).ratio(),
        difflib.SequenceMatcher(None, typed, word[: len(typed)]).ratio(),
    )
    return ratio * 0.8 if ratio >= TYPO_RATIO else 0.0


def list_score(query: str, entry: Listed) -> float:
    """How well the query matches a list masjid, from 0 (no match) to 1.

    Every word typed has to match something, so "barrhaven mosque" finds
    Barrhaven Islamic Centre ("mosque" is a common word, so it's skipped),
    but "barrhaven omar" finds nothing.
    """
    typed = name_words(query)
    words = name_words(entry.name) + name_words(entry.short_name)
    if not typed or not words:
        return 0.0
    scores = [max(word_score(t, w) for w in words) for t in typed]
    if min(scores) == 0:
        return 0.0
    return sum(scores) / len(scores)


def search_list(query: str, entries: list[Listed], home: tuple[float, float]) -> list[Suggestion]:
    """List masjids matching the query, best first, then nearest. At most 5."""
    scored = [(list_score(query, e), e) for e in entries]
    found = sorted(
        ((score, e) for score, e in scored if score > 0),
        key=lambda pair: (-round(pair[0], 2), distance_km(*home, pair[1].latitude, pair[1].longitude)),
    )
    return [
        Suggestion(
            label=e.name,
            latitude=e.latitude,
            longitude=e.longitude,
            country_code=None,
            kind="masjid",
            name=e.name,
            street_address=e.address,
            list_external_id=e.external_id,
        )
        for _, e in found[:MAX_SUGGESTIONS]
    ]


# The same name this close is the same masjid, even when OpenStreetMap's pin
# is further off than auto-linking allows (200 m).
SAME_NAME_WITHIN_KM = 2


def _same_masjid(place: Suggestion, shown: list[Listed]) -> bool:
    """True when a Photon result is a list masjid that's already shown."""
    if match(place.latitude, place.longitude, place.name, shown).status != "no match":
        return True
    words = name_words(place.name)
    return any(
        words == name_words(e.name) and distance_km(place.latitude, place.longitude, e.latitude, e.longitude) <= SAME_NAME_WITHIN_KM
        for e in shown
    )


def suggest(db: Session, http: httpx2.Client, query: str, home: tuple[float, float], now: datetime) -> list[Suggestion]:
    """Up to 5 masjids for what's typed: list matches first, then Photon's, with no duplicates."""
    if len(normalize(query)) < MIN_QUERY_LENGTH:
        return []
    entries = listed(db)
    found = search_list(query, entries, home)
    if len(found) >= MAX_SUGGESTIONS:
        return found
    try:
        places = suggest_masjids(db, http, query, home, now)
    except OsmServiceError:
        # Photon is down. The list still works, so only fail when it found nothing.
        if found:
            return found
        raise
    by_id = {e.external_id: e for e in entries}
    shown = [by_id[s.list_external_id] for s in found]
    found += [p for p in places if not (p.kind == "masjid" and _same_masjid(p, shown))]
    return found[:MAX_SUGGESTIONS]


def from_list(suggestion: Suggestion) -> bool:
    return suggestion.list_external_id is not None

