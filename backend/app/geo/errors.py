"""Errors from OpenStreetMap's services."""


class OsmServiceError(Exception):
    """Nominatim or Overpass is down, busy, or gave an answer we can't use.

    The message is shown to the user, so it never includes their address.
    """
