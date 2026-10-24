"""Entry point for the backend.

Uvicorn (the web server) loads the `app` object from this file.
Run locally with:  uvicorn app.main:app --reload
"""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_engine
from app.routers import prayer_times

app = FastAPI(title="Muslim Calendar API")
app.include_router(prayer_times.router)


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
