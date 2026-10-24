"""Errors from talking to Google, so callers can react to each kind."""


class GoogleError(Exception):
    """Google said no, and trying again won't help."""


class GoogleTemporaryError(GoogleError):
    """A timeout, rate limit (429), or Google server error (5xx). Try again later."""


class GoogleNotFound(GoogleError):
    """404 or 410: the calendar or event isn't there, for example the user deleted it."""


class GoogleConflict(GoogleError):
    """409: an event with this ID already exists."""


class ReauthRequired(Exception):
    """Google refused the refresh token, so the user has to sign in again.

    In Testing mode Google expires refresh tokens after 7 days. A user can
    also remove the app's access from their Google account.
    """


class CalendarAccessMissing(Exception):
    """The user signed in but unticked calendar access on Google's consent screen."""
