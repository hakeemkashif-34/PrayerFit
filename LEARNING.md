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
   c) FastAPI turns the returned dict into JSON: `{"status": "ok"}`.
   d) Why a health check: Docker, CI, and Azure need a cheap way to ask "did the server start?"
   e) It doesn't touch the database on purpose, so it answers even if Postgres is down. A separate "is the database reachable" check can come later.

2. **`app/__init__.py`**
   a) Empty file that makes `app` a Python package, so `from app.main import app` works.

3. **`requirements.txt`**
   a) Packages the app needs to run: `fastapi` (the framework) and `uvicorn` (the web server that runs it).
   b) Versions are pinned (`==`) so your laptop, CI, and Docker all install the same thing.

4. **`requirements-dev.txt`**
   a) Starts with `-r requirements.txt`, then adds testing tools.
   b) Kept separate so the Docker image doesn't ship test tools it never uses.
   c) `httpx2` is what FastAPI's `TestClient` uses to send fake requests. The older `httpx` still works but prints a deprecation warning.

### 3. Tests

1. **`tests/test_health.py`**
   a) Calls `/health` and checks for status 200 and `{"status": "ok"}`.
   b) `TestClient` runs the app in memory. No server, no Docker, no database needed, so tests are fast and run anywhere.
   c) pytest finds any function starting with `test_` in a file starting with `test_`.

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
   d) `volumes: db-data` keeps the database's data when containers are removed. `docker compose down -v` deletes it.
   e) The `healthcheck` runs `pg_isready`. With `condition: service_healthy`, the backend waits until Postgres accepts connections, not just until its container starts.
   f) `$${POSTGRES_USER}` has two `$` so Compose passes `$POSTGRES_USER` to the container's shell instead of filling it in itself.

### 5. GitHub Actions

1. **`.github/workflows/tests.yml`**
   a) On every push and pull request, GitHub starts a fresh Ubuntu machine, installs Python 3.13 and the packages, and runs `pytest`.
   b) A red X on a commit or PR means a test failed.
   c) `cache: pip` saves downloaded packages between runs, so later runs are faster.
   d) Python 3.13 matches the Dockerfile, so tests run on the same version as the real app.
