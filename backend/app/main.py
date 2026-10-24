"""Entry point for the backend.

Uvicorn (the web server) loads the `app` object from this file.
Run locally with:  uvicorn app.main:app --reload
"""

from fastapi import FastAPI

app = FastAPI(title="Muslim Calendar API")


@app.get("/health")
def health() -> dict[str, str]:
    """Tell callers the server is up.

    Docker Compose, GitHub Actions, and later Azure call this to check
    that the app started. It doesn't touch the database, so it still
    answers even if Postgres is down.
    """
    return {"status": "ok"}
