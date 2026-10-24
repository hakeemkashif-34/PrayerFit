# Learning Notes

What each part of the app does and why it was built that way. Updated after each milestone.

---

## Milestone 1: Setup

### 1. Repo basics

1. **`.gitignore`**
   a) Tells git which files never to commit.
   b) Most important line: `.env`, so real passwords and keys stay on your machine.
   c) Also skips generated junk like `__pycache__/`, `.venv/`, and `node_modules/`.

2. **`.env.example`**
   a) A template listing every setting the app needs, with fake values.
   b) You copy it to `.env` and fill in real values.
   c) Why: new developers (and CI, and Azure later) can see what's needed without anyone sharing secrets.

3. **`README.md`**
   a) How to run the app and the tests. The first thing a recruiter or teammate reads.

### 2. Backend (`backend/`)

1. **`app/main.py`**
   a) Creates the FastAPI app and the `/health` endpoint.
   b) `@app.get("/health")` means "when a GET request comes to /health, run this function".
   c) Why a health check: Docker, CI, and Azure need a cheap way to ask "is the app working?"
   d) It runs `SELECT 1`, the smallest possible query, to prove Postgres answers.
   e) Database up: status 200 and `{"status": "ok", "database": "ok"}`.
   f) Database down: status 503 and `{"status": "error", "database": "unreachable"}`.
   g) Why 503 (Service Unavailable): the server itself is running, but it can't do its job. Azure and other tools treat any 5xx as "unhealthy", so they can restart the app or stop sending it traffic. Returning 200 with "error" in the body would look healthy to them.
   h) `Depends(get_engine)` is FastAPI's dependency injection. FastAPI calls `get_engine()` and passes the result in. Because the engine isn't hard-coded, tests can swap in a different one.
   i) Only `SQLAlchemyError` is caught, so a database problem gives a 503, but a typo in our own code still shows up as a normal error instead of being hidden.

2. **`app/db.py`**
   a) Sets up the connection to Postgres.
   b) The **engine** is SQLAlchemy's connection manager. It keeps a pool of open connections so each request doesn't open a new one.
   c) `database_url()` reads `DATABASE_URL` from the environment and fails with a clear message if it's missing.
   d) It changes `postgresql://` to `postgresql+psycopg://`. Without that, SQLAlchemy looks for the older `psycopg2` driver, which isn't installed.
   e) `@lru_cache` on `get_engine()` means the engine is made once, on the first request, then reused.
   f) It's made on first use, not when the app starts, so the app can still start and report a 503 when the database is down.
   g) `pool_pre_ping=True` checks a pooled connection still works before using it. Without it, the first request after a Postgres restart would fail on a dead connection.
   h) `connect_timeout: 3` gives up after 3 seconds, so `/health` answers quickly instead of hanging when the database can't be reached.

3. **`app/__init__.py`**
   a) Empty file that makes `app` a Python package, so `from app.main import app` works.

4. **`requirements.txt`**
   a) Packages the app needs to run: `fastapi` (the framework), `uvicorn` (the web server that runs it), `sqlalchemy` (talks to the database), and `psycopg` (the Postgres driver SQLAlchemy uses).
   b) `psycopg[binary]` comes with its own compiled copy of the Postgres client library, so nothing extra needs installing on your laptop or in Docker.
   c) Versions are pinned (`==`) so your laptop, CI, and Docker all install the same thing.

5. **`requirements-dev.txt`**
   a) Starts with `-r requirements.txt`, then adds testing tools.
   b) Kept separate so the Docker image doesn't ship test tools it never uses.
   c) `httpx2` is what FastAPI's `TestClient` uses to send fake requests. The older `httpx` still works but prints a deprecation warning.

### 3. Tests

1. **`tests/test_health.py`**
   a) `test_health_ok_when_database_is_up`: calls `/health` against a real Postgres and expects 200.
   b) `test_health_503_when_database_is_down`: expects 503 and the "unreachable" message.
   c) `TestClient` runs the app in memory, so no web server is needed. A real Postgres is needed, found through `DATABASE_URL`.
   d) Why a real database instead of a fake one: a fake only proves the code calls the fake correctly. A real one proves the app can actually connect, with the real driver and real connection settings.
   e) The "down" test uses a **fixture**, `database_down`. pytest runs the code before `yield` before the test and the code after `yield` after it, even if the test fails.
   f) The fixture uses `app.dependency_overrides` to make FastAPI use an engine pointing at port 1 on this machine, where nothing is listening. The connection is refused straight away, like a database that's down.
   g) After the test, the fixture clears the override so later tests use the real database again.
   h) The real database is never stopped, so the tests stay fast and don't affect each other.
   i) pytest finds any function starting with `test_` in a file starting with `test_`.

2. **`pytest.ini`**
   a) `testpaths = tests`: where to look for tests.
   b) `pythonpath = .`: lets tests import `app` from the `backend` folder.

### 4. Docker

1. **`backend/Dockerfile`**
   a) A recipe for building an image: a small Linux system with Python and the app inside.
   b) `requirements.txt` is copied and installed before the code. Docker caches each step, so changing code doesn't reinstall every package.
   c) Runs as a normal user, not root, so a bug in the app can't take over the container.
   d) `--host 0.0.0.0` makes the server reachable from outside the container. The default (`127.0.0.1`) only listens inside it.

2. **`backend/.dockerignore`**
   a) Keeps `.venv`, caches, and tests out of the image so it stays small.

3. **`docker-compose.yml`**
   a) Runs two containers together: `db` (Postgres 17) and `backend`.
   b) `${POSTGRES_USER}` and the others are read from `.env`.
   c) Inside Compose, containers reach each other by service name. That's why `DATABASE_URL` uses `@db:5432`, not `localhost`.
   d) From your laptop (for example when running the tests), the database is at `localhost:5432` instead, because Compose publishes port 5432.
   e) `volumes: db-data` keeps the database's data when containers are removed. `docker compose down -v` deletes it.
   f) The `healthcheck` runs `pg_isready`. With `condition: service_healthy`, the backend waits until Postgres accepts connections, not just until its container starts.
   g) `$${POSTGRES_USER}` has two `$` so Compose passes `$POSTGRES_USER` to the container's shell instead of filling it in itself.

### 5. GitHub Actions

1. **`.github/workflows/tests.yml`**
   a) On every push and pull request, GitHub starts a fresh Ubuntu machine, installs Python 3.13 and the packages, and runs `pytest`.
   b) `services: postgres` starts a real Postgres 17 container next to the tests, the same version as Docker Compose.
   c) The health options make GitHub wait until Postgres accepts connections before running the tests, the same idea as the Compose healthcheck.
   d) `DATABASE_URL` is set for the whole job so the tests can find it. The username and password are throwaway test values, not secrets. That database only exists while the job runs.
   e) A red X on a commit or PR means a test failed.
   f) `cache: pip` saves downloaded packages between runs, so later runs are faster.
   g) Python 3.13 matches the Dockerfile, so tests run on the same version as the real app.

### 6. How to check it works

1. **Tests on your laptop**
   a) Start only the database: `docker compose up -d db`.
   b) In `backend`, activate the virtual environment and install `requirements-dev.txt`.
   c) Point the tests at the database: `export DATABASE_URL=postgresql://muslim_calendar:change-me@localhost:5432/muslim_calendar` (use your `.env` values).
   d) Run `pytest`. You should see `2 passed`.

2. **The whole app in Docker**
   a) Run `docker compose up --build` and open http://localhost:8000/health. You should see `"database":"ok"`.
   b) In another terminal, run `docker compose stop db` and refresh. You should get a 503 and `"database":"unreachable"`.
   c) Run `docker compose start db` and refresh. It goes back to ok.

3. **GitHub Actions**
   a) Open the PR and look for the green check next to "Tests". The Actions tab shows the full log.
