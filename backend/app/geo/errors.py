"""Errors from Photon, the search built on OpenStreetMap data."""


class OsmServiceError(Exception):
    """Photon is down, busy, or gave an answer we can't use.

    The message is shown to the user, so it never includes their address.
    """
