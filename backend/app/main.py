"""Entry point for the backend.

Uvicorn (the web server) loads the `app` object from this file.
Run locally with:  uvicorn app.main:app --reload
"""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_app_settings
from app.db import get_engine
from app.geo.errors import OsmServiceError
from app.google_errors import CalendarAccessMissing, ReauthRequired
from app.routers import auth, prayer_times, prayers, settings, stats

app = FastAPI(title="Muslim Calendar API")
app.include_router(prayer_times.router)
app.include_router(auth.router)
app.include_router(prayers.router)
app.include_router(settings.router)
app.include_router(stats.router)


@app.exception_handler(ReauthRequired)
def ask_to_sign_in_again(request: Request, error: ReauthRequired) -> JSONResponse:
    # A dead refresh token is normal (7 days in Testing mode), not a crash.
    return JSONResponse(
        status_code=401,
        content={
            "detail": {
                "message": "Google sign-in expired. Sign in again.",
                # The website shows "Sign in again" instead of an error for this one.
                "reason": "google_sign_in_expired",
                "login_url": "/auth/google/login",
            }
        },
    )


@app.exception_handler(CalendarAccessMissing)
def ask_for_calendar_access(request: Request, error: CalendarAccessMissing) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "detail": {
                "message": "Sign in again and allow calendar access.",
                "reason": "calendar_access_missing",
                "login_url": "/auth/google/login",
            }
        },
    )


@app.exception_handler(OsmServiceError)
def osm_unavailable(request: Request, error: OsmServiceError) -> JSONResponse:
    # 503: OpenStreetMap is busy or down, so try again later.
    return JSONResponse(status_code=503, content={"detail": {"message": str(error)}})


# Methods that change something. GET requests must never change data.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def check_origin(request: Request, call_next):
    """Refuse changes that come from another website.

    Browsers always send an Origin header with a POST, saying which site
    the page was on. If it isn't this app, a page elsewhere is trying to
    use the user's cookie, so the request is refused. This backs up the
    SameSite=Lax cookie. A missing Origin is refused too.
    """
    if request.method in UNSAFE_METHODS:
        if request.headers.get("origin") != get_app_settings().origin:
            return JSONResponse(
                status_code=403,
                content={"detail": "Request came from another site, so it was refused."},
            )
    return await call_next(request)


@app.get("/health")
def health(engine: Annotated[Engine, Depends(get_engine)]):
    """Tell callers whether the server and the database are working.

    Docker Compose, GitHub Actions, and later Azure call this to check the app.
    It runs the smallest possible query, SELECT 1, to prove Postgres answers.

    The engine comes in through Depends, so tests can swap in a different one
    (for example, one pointing at a database that's down).
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # 503 Service Unavailable: the server is running but can't do its job.
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable"},
        )
    return {"status": "ok", "database": "ok"}
