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
   c) Point the tests at the database: `export DATABASE_URL=postgresql://prayerfit:change-me@localhost:5432/prayerfit` (use your `.env` values).
   d) Run `pytest`. You should see `2 passed`.

2. **The whole app in Docker**
   a) Run `docker compose up --build` and open http://localhost:8000/health. You should see `"database":"ok"`.
   b) In another terminal, run `docker compose stop db` and refresh. You should get a 503 and `"database":"unreachable"`.
   c) Run `docker compose start db` and refresh. It goes back to ok.

3. **GitHub Actions**
   a) Open the PR and look for the green check next to "Tests". The Actions tab shows the full log.

---

## Milestone 2: Prayer times

### 1. Where things are

1. **`backend/app/prayer_times/`**: the calculation. Pure maths, no database and no web code, so it's easy to test.
   a) `astronomy.py`: where the sun is, and when it reaches a given height in the sky.
   b) `methods.py`: the calculation methods (ISNA and others) and the Asr methods.
   c) `calculator.py`: puts it together into Fajr, Sunrise, Dhuhr, Asr, Maghrib, and Isha for one place and one day.
   d) `__init__.py`: lists what other files can import, so they write `from app.prayer_times import calculate_prayer_times`.
2. **`backend/app/routers/prayer_times.py`**: the `GET /prayer-times` endpoint.
   a) A router is a group of endpoints in its own file. `main.py` adds it with `app.include_router(...)`. This keeps `main.py` small as more endpoints come.

### 2. How prayer times are worked out

Every prayer time is "the moment the sun is at a certain height". The height is called the **altitude**, in degrees. 0 is the horizon, negative is below it.

| Prayer | When it starts |
|---|---|
| Fajr | Sun is 15 to 19.5 degrees below the horizon, before sunrise (depends on the method) |
| Sunrise | Top of the sun at the horizon. Ends Fajr. |
| Dhuhr | Just after the sun is highest (solar noon) |
| Asr | A stick's shadow equals its noon shadow plus 1 stick length (Hanafi: 2) |
| Maghrib | Sunset |
| Isha | Sun is 15 to 18 degrees below the horizon, after sunset (Umm al-Qura: 90 minutes after Maghrib) |

So the job is: (1) know where the sun is at any moment, and (2) find the moment it reaches each altitude.

### 3. `astronomy.py`

1. **Where the formulas come from**
   a) Jean Meeus, "Astronomical Algorithms". It's the standard book for this. The adhan library uses it too, which is why our times can be compared with it.
   b) Each function names the chapter it comes from.

2. **`julian_day`**
   a) Counts days from a fixed start point instead of using year, month, day.
   b) Why: the gap between two dates becomes a subtraction. No months or leap years to handle.

3. **`sun_position`**
   a) Gives three numbers for midnight UTC on a date.
   b) **Declination**: how far north or south of the equator the sun is. About +23.4 in June, -23.4 in December. This is why summer days are long.
   c) **Right ascension**: the sun's position along the sky, like a longitude for the sky.
   d) **Sidereal time**: how far the Earth has turned, measured against the stars.

4. **`SolarDay`**
   a) Works out the sun for yesterday, today, and tomorrow, then estimates any moment in between (interpolation, chapter 3). The sun moves smoothly, so three points are enough.
   b) **Hour angle**: how far the sun is past this place's meridian (the north-south line overhead). 0 at solar noon.
   c) `noon()`: solar noon, when the hour angle is 0.
   d) `time_at_altitude(target, after_noon)`: when the sun is at the target altitude. Returns `None` if it never gets there that day.

5. **Why `time_at_altitude` uses binary search**
   a) From solar noon to solar midnight, the sun only goes down. So the answer is somewhere in that half day.
   b) Check the middle. If the sun is still above the target, the answer is in the later half. Otherwise the earlier half. Repeat.
   c) Each step halves the gap. About 23 steps get from half a day to 0.01 seconds.
   d) If the sun is still above the target at midnight (or below it at noon), there's no answer. That's how we know it never gets dark enough.
   e) Why not the book's method: the book guesses a time and corrects it once. That's fast and usually within seconds. But on days when the sun only just reaches the target (Fajr at 18 degrees in London or Edmonton), I measured it up to 4 minutes off. Repeating the correction fixed that, but at Alert it jumped to the wrong day. Binary search can't do either. I checked it against a minute-by-minute scan and it matched to 0.003 seconds.

6. **Sunrise altitude is -0.833, not 0**
   a) The air bends light, so you see the sun about 0.57 degrees before it's really over the horizon.
   b) Sunrise is when the top of the sun shows, not the centre. That's another 0.27 degrees (half the sun's width).

### 4. `methods.py`

1. **Calculation methods**: different groups of scholars disagree on how dark it has to be for Fajr and Isha.

| Method | Fajr angle | Isha |
|---|---|---|
| `isna` (default) | 15 | 15 |
| `mwl` | 18 | 17 |
| `egyptian` | 19.5 | 17.5 |
| `karachi` | 18 | 18 |
| `umm_al_qura` | 18.5 | 90 minutes after Maghrib |

2. ISNA is the default because most masjids in Ottawa use it.
3. Umm al-Qura uses 120 minutes in Ramadan. That isn't handled yet. It's noted in the code.
4. **Dhuhr is 1 minute after solar noon** for every method except Umm al-Qura.
   a) Solar noon is when the centre of the sun crosses the meridian. The sun is about 2 minutes wide, so its back edge crosses about 1 minute later.
   b) These values match the adhan library.
   c) Example: Ottawa on October 24, 2026. Solar noon is 12:46:57. Plus 1 minute is 12:47:57, which rounds up to **12:48**. Rounding solar noon alone would give 12:47, so the extra minute is on purpose. Since milestone 4, Dhuhr's event description says this, with that day's solar noon.
   d) Other sites may say 12:46:55 for solar noon. Solar formulas differ by a couple of seconds. That doesn't change the answer.
5. **Asr methods**: `standard` (Shafi'i, Maliki, Hanbali) uses 1 shadow length. `hanafi` uses 2, so Hanafi Asr is always later.
6. `StrEnum` makes each choice a string, like `"isna"`. FastAPI uses that to check the URL and to show the choices on `/docs`.

### 5. `calculator.py`

1. **`calculate_prayer_times(latitude, longitude, on_date, time_zone, method, asr_method)`**
   a) `on_date` is a local date, like a date on a wall calendar.
   b) `time_zone` defaults to `America/Toronto`.
   c) Returns a `DailyPrayerTimes` with six `PrayerTime`s.

2. **All the maths is in UTC**
   a) UTC has no daylight saving, so adding hours is always safe.
   b) Only at the end is each time converted to the local zone with `.astimezone(zone)`.
   c) Next day means the next calendar date (`date + timedelta(days=1)` on a `date`), never "add 24 hours". On a daylight saving day, a local day is 23 or 25 hours long.

3. **`_utc_day_for`**: picks the UTC date whose solar noon falls on the local date.
   a) Almost always it's the same date.
   b) Near the date line (Samoa, for example) it's the day before or after. Without this, you'd get the wrong day's times.

4. **Asr uses the sun's declination at solar noon**
   a) The rule compares with the noon shadow, so the noon shadow should use where the sun is at noon.
   b) adhan uses where the sun is at midnight UTC instead, which is 5 or 6 pm the day before in Edmonton. That moves Asr by up to 2 minutes there.

5. **Rounding**
   a) `round_up_to_minute` for Fajr, Dhuhr, Asr, Maghrib, and Isha. 12:00:01 shows as 12:01. The app never shows a prayer before it starts.
   b) `round_down_to_minute` for sunrise. Sunrise ends Fajr, so showing it a little early is the safe side.
   c) Rounding happens in UTC. Every time zone in use today is a whole number of minutes from UTC, so this gives the same answer as rounding the local time.

6. **High latitude rules**
   a) In Edmonton in June the sun only goes about 13 degrees below the horizon. It never reaches the 15 that ISNA uses, so there's no normal Fajr or Isha.
   b) Instead of an error, the app uses a share of the night (sunset to sunrise).
   c) Below 48 degrees: Fajr no earlier than the middle of the night, Isha no later. Same cut-off as adhan's recommended rule.
   d) From 48 degrees: Fajr no earlier than the last seventh of the night, Isha no later than the first seventh. Summer nights up there are short, so half the night would be too loose.
   e) The limit is used whenever the normal time is missing or goes past it.
   f) Fajr uses the night it ends (last sunset to this sunrise). Isha uses the night it starts (this sunset to tomorrow's sunrise). Because both use the same night, Isha can never run past the next Fajr. adhan uses tonight for Fajr too, which moves it by up to about 40 seconds in late summer.
   g) Above 65 degrees (Inuvik, Alert, Antarctica), some days have no sunset (midnight sun) or no sunrise (polar night). The app uses the times at 65 degrees, the nearest latitude where the sun rises and sets every day.
   h) It does that every day, not just on days with no sunrise or sunset. The days next to those have only minutes of daylight or darkness. Asr lands on Dhuhr, and switching rules made times jump by over an hour from one day to the next.

7. **Where each time came from**
   a) Every `PrayerTime` has `source = "calculated"`, the `method`, the `asr_method`, and `high_latitude_rule` (`None` unless a rule replaced the time).
   b) Later, masjid times will have their own source, so users can tell calculated times and iqamah times apart.
   c) `exact_time` keeps the time before rounding, in UTC. The tests use it. The endpoint doesn't show it.

### 6. `GET /prayer-times`

1. Takes `latitude`, `longitude`, `date`, `method`, `asr_method`, and `timezone`. Only latitude and longitude are required.
2. Example: `/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24`

```json
{
  "date": "2026-10-24",
  "timezone": "America/Toronto",
  "latitude": 45.4215,
  "longitude": -75.6972,
  "method": "isna",
  "asr_method": "standard",
  "times": {
    "fajr": {"time": "2026-10-24T06:10:00-04:00", "source": "calculated", "method": "isna", "asr_method": "standard", "high_latitude_rule": null},
    "sunrise": {"time": "2026-10-24T07:31:00-04:00", "...": "..."},
    "dhuhr": {"time": "2026-10-24T12:48:00-04:00", "...": "..."},
    "asr": {"time": "2026-10-24T15:35:00-04:00", "...": "..."},
    "maghrib": {"time": "2026-10-24T18:03:00-04:00", "...": "..."},
    "isha": {"time": "2026-10-24T19:24:00-04:00", "...": "..."}
  }
}
```

3. Times include the offset (`-04:00`), so anyone reading them knows exactly which moment it is.
4. No date means today in that time zone, not the server's. The server on Azure will most likely run on UTC.
5. The default time zone comes from `DEFAULT_TIMEZONE` in `.env`, then `America/Toronto`.
6. Bad input gives 422 (Unprocessable Content). FastAPI checks the numbers, date, and method names by itself from the type hints. The time zone is checked by hand, since any string could be sent.
7. `../../etc/passwd` as a time zone also gives 422. `ZoneInfo` refuses names that try to leave the time zone folder, and the endpoint turns that error into a 422.
8. The Python name is `on_date` with `alias="date"`, so the URL still says `date` but the code doesn't hide Python's `date` type.
9. `tzdata` in `requirements.txt` gives Python the time zone rules on computers that don't have them, like Windows.

### 7. Tests

1. **`tests/places.py`**: the places and years every test shares. 7 cities to compare with other libraries, plus St. John's (a half hour time zone), Iqaluit, Inuvik, Alert, and McMurdo Station for the far north and south.

2. **`test_prayer_times_reference.py`**: compares with two well-known libraries, every day of 2026 and 2028 (a leap year), for Ottawa, Toronto, Edmonton, Mecca, London, Sydney, and Karachi.
   a) adhanpy (the Python version of adhan) for Fajr, Sunrise, Dhuhr, Maghrib, and Isha, for all 5 methods.
   b) praytimes (the Python version of PrayTimes.org) for Asr, standard and Hanafi.
   c) Both are in `requirements-dev.txt` only. The app never uses them.
   d) Every time must match within 1 minute. In practice the worst gap with adhanpy is 10 seconds, and with PrayTimes about 25 seconds for Asr.
   e) Asr is compared with PrayTimes because adhanpy uses the wrong declination for Asr (see section 5, point 4). PrayTimes uses the declination at Asr, which is within 25 seconds of ours.
   f) Fajr is checked against adhanpy's own sunrise and sunset times with our night rule applied, because adhanpy uses a different night for the high latitude rule (section 5, point 6f).
   g) Times are compared before rounding. adhanpy rounds to the nearest minute and we round up, so rounded times can be a minute apart even when the maths agrees. adhanpy also has a bug at :59 (12:59:45 shows as 12:59, not 13:00).
   h) To get adhanpy's times before rounding, a **fixture** uses `monkeypatch` to swap its rounding function for one that does nothing, only during that test.
   i) I broke the code on purpose (a wrong Fajr angle, a wrong Dhuhr offset, the wrong Asr declination) to check the tests fail. They did.

3. **`test_daylight_saving.py`**: Toronto's clock changes on March 8 and November 1, 2026.
   a) Every time in the week around each change is on the right date with the right offset (-05:00 or -04:00).
   b) On the wall clock, every prayer jumps by about an hour. In real time, one Dhuhr to the next is still about 24 hours.
   c) A Python trap: subtracting two times in the same `ZoneInfo` compares wall clocks. The March 7 to March 8 Dhuhr gap comes out as 25 hours. Converting both to UTC first gives the real gap. The tests do that everywhere times are compared.

4. **`test_prayer_times_rules.py`**
   a) Rounding: start times are never before the exact time and less than a minute after it. Sunrise is the other way round.
   b) Every time says `"calculated"` plus its method and Asr method.
   c) Order: Fajr < Sunrise < Dhuhr < Asr < Maghrib < Isha, and Isha is never after the next day's Fajr. Every place, every method, every day of 2026.
   d) Hanafi Asr is always later than standard Asr, every place, every day.
   e) These tests found two real bugs: the jump to the wrong day at Alert, and Asr landing in the same minute as Dhuhr near the poles. Those led to the binary search and to using 65 degrees every day.

5. **`test_high_latitude.py`**
   a) Edmonton in June: proves the sun never reaches 15 degrees, then checks Fajr and Isha are exactly one seventh of the right night.
   b) St. John's in June with the Egyptian method: checks the middle of the night rule.
   c) Ottawa and Mecca: no rule is ever used, every day, every method. The rules must never touch normal times.
   d) Inuvik on June 21 (midnight sun) and December 21 (polar night), and McMurdo Station: times match the ones at 65 degrees.

6. **`test_prayer_times_endpoint.py`**: the endpoint returns all six times in order, matches the calculator, shows sources and the high latitude rule, uses the time zone, and gives 422 for bad input.

### 8. How to check it works

1. **Tests**
   a) Start the database and set `DATABASE_URL` like in milestone 1, then run `pytest` in `backend`. You should see `235 passed`.
   b) Only the prayer time tests (no database needed): `pytest -k "not health"`. You should see `233 passed, 2 deselected`.

2. **In the browser**
   a) Run `docker compose up --build`.
   b) Open http://localhost:8000/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24. Fajr should be `06:10`, Maghrib `18:03`.
   c) Add `&asr_method=hanafi`. Asr moves later.
   d) Try Edmonton in June: http://localhost:8000/prayer-times?latitude=53.5461&longitude=-113.4938&date=2026-06-21&timezone=America/Edmonton. Fajr and Isha show `"high_latitude_rule": "seventh_of_the_night"`.
   e) Try a bad time zone, like `&timezone=Mars/Olympus_Mons`. You get a 422.
   f) http://localhost:8000/docs shows the endpoint with every choice in a dropdown.

3. **GitHub Actions**: the PR's "Tests" check runs all 235 tests.

---

## Milestone 3: Google Calendar

### 1. Where things are

1. **`backend/app/config.py`**: reads the Google keys and app settings from the environment. Google keys are only read when a Google endpoint runs, so `/health` works without them.
2. **`backend/app/models.py`**: the database tables (users, sessions, Google tokens, Prayers calendars, prayer events).
3. **`backend/alembic/`** and **`alembic.ini`**: migrations, the history of changes to the tables.
4. **`backend/app/auth/`**: sign-in.
   a) `google_oauth.py`: PKCE, the Google sign-in URL, swapping the code for tokens, refreshing, and reading the ID token.
   b) `crypto.py`: encrypts tokens before they're saved.
   c) `tokens.py`: saves tokens and hands out a working access token, refreshing it when needed.
   d) `sessions.py`: the session cookie and the `current_user` dependency.
5. **`backend/app/routers/auth.py`**: `/auth/google/login`, `/auth/google/callback`, `/auth/logout`, `/me`.
6. **`backend/app/google_calendar.py`**: the only code that talks to the Calendar API. 4 calls, nothing else.
7. **`backend/app/prayers_calendar.py`**: finds, reuses, or recreates the "Prayers" calendar.
8. **`backend/app/prayer_sync.py`**: turns prayer times into events, saves them, and sends them to Google without duplicates.
9. **`backend/app/routers/prayers.py`**: `POST /prayers/today` and `GET /prayers/today/events`.
10. **`backend/app/google_errors.py`**: one error type per kind of Google problem.
11. **`backend/app/google_http.py`** and **`backend/app/clock.py`**: the HTTP client and the current time, as dependencies, so tests can swap them.

### 2. Database and migrations

1. **SQLAlchemy models** describe each table as a Python class. `Mapped[str]` means a column that can't be empty. `Mapped[str | None]` means it can be.
2. **Every table has `user_id`** (except `users`). Every query filters on it. That's how one user can never see another's data.
3. **Alembic** keeps a numbered list of changes to the tables. `alembic upgrade head` applies any that haven't run yet, and records which ran in a table called `alembic_version`.
4. I made the first migration with `alembic revision --autogenerate`, which compares the models with the empty database and writes the `create_table` calls. Then I read it and tidied it.
5. `alembic/env.py` reads `DATABASE_URL` through `app/db.py`, so no password is in `alembic.ini`.
6. Docker runs `alembic upgrade head` before starting the server. The tests run the same migrations once, in `conftest.py`.
7. `test_migrations.py` checks the models and the migrations match. If someone changes a model and forgets a migration, it fails.
8. `get_db` in `app/db.py` gives each request its own database session and closes it after.
9. `expire_on_commit=False`: by default SQLAlchemy forgets every loaded value after a commit and reloads it on the next read. The prayers endpoint commits after each Google call and keeps using the rows, so I turned that off.

### 3. Signing in with Google (OAuth)

1. **The flow** (authorization code flow), all on the server:
   a) `/auth/google/login` sends the browser to Google with a random `state` and a PKCE `code_challenge`.
   b) The user picks an account and clicks Allow.
   c) Google sends the browser to `/auth/google/callback?code=...&state=...`.
   d) The server checks the state, then sends the code and the PKCE `code_verifier` to Google's token endpoint, and gets tokens back.
   e) The browser never sees a Google token. It only gets a session cookie.

2. **State** stops login CSRF. Without it, someone could send me a link that finishes *their* sign-in in *my* browser, and my prayers would go into their calendar. The state is random, stored in a cookie tied to my browser, and has to match what comes back.

3. **PKCE** (Proof Key for Code Exchange, said "pixie")
   a) The server makes a random `code_verifier` and sends Google only its SHA-256 hash, the `code_challenge`.
   b) When swapping the code for tokens, the server sends the verifier. Google hashes it and checks it matches.
   c) Why: if someone steals the code from the redirect (a browser extension, a log), they can't use it without the verifier, which never left the server.
   d) `S256` means the challenge is a SHA-256 hash, not the verifier itself.

4. **The `oauth_flow` cookie** holds the state and verifier between the two requests.
   a) Encrypted with the same Fernet key as the tokens, so the browser can't read or change it.
   b) `Max-Age=600` and Fernet's own time check: the sign-in has to finish within 10 minutes.
   c) `Path=/auth/google`, so it's only sent to the sign-in endpoints.
   d) Deleted on every callback answer, success or failure, so each sign-in flow works once.
   e) I used a cookie instead of a table because it's tied to the browser and needs no cleanup.

5. **Scopes**: `openid` and `email` say who I am. `calendar.app.created` lets the app create its own calendars and manage events on them only. It can't read or change any other calendar. No Gmail, no full calendar access.

6. **`access_type=offline`** asks for a refresh token. **`prompt=consent`** shows the consent screen every time, because Google only sends a refresh token when consent is shown.

7. **Unticked calendar box**: Google lets users untick a scope. The callback saves which scopes came back. Without the calendar one, `/me` shows `"calendar_access": false` and `POST /prayers/today` answers 403 "Sign in again and allow calendar access."

8. **The ID token** is a JWT (3 base64 parts joined by dots) that says who signed in.
   a) I read `sub` (Google's permanent user ID) and `email`. Users are matched by `sub`, since emails can change.
   b) I check the issuer is Google, the audience is my client ID, and it hasn't expired.
   c) I skip the signature check. The OpenID Connect spec (section 3.1.3.7) allows that when the token came straight from Google's token endpoint over HTTPS in the server's own request.

### 4. Tokens

1. **Access token**: lasts about 1 hour. Sent with every Calendar API call.
2. **Refresh token**: used to get a new access token. In Testing mode Google expires it after 7 days.
3. **Encryption** (`crypto.py`): Fernet, from the `cryptography` package. AES encryption plus a signature.
   a) A copy of the database without `TOKEN_ENCRYPTION_KEY` from `.env` is useless.
   b) The signature means a changed value fails to decrypt instead of becoming garbage.
   c) Each encryption adds a random IV, so the same token encrypts differently every time.
   d) If the key is lost or changed, nobody's tokens decrypt and everyone has to sign in again.
4. **Refreshing** (`get_access_token` in `tokens.py`):
   a) If the saved access token has more than 60 seconds left, use it. The margin stops it expiring mid-request.
   b) Otherwise refresh with Google and save the new one.
   c) If Google answers `invalid_grant`, the refresh token is dead. The app sets `needs_reauth`, and the API answers 401 with `"Google sign-in expired. Sign in again."` and `login_url`. No crash.
   d) If the Calendar API rejects a token we thought was fine (401), the client refreshes once and tries once more.
   e) Signing in again saves new tokens and clears `needs_reauth`.

### 5. Sessions and cross-site protection

1. **Session cookie**: `secrets.token_urlsafe(32)`, 256 random bits.
2. **Only the hash is saved**: the `sessions` table has the SHA-256 of the cookie. Someone who reads the database can't sign in with it. SHA-256 without a salt is fine here because the value is random and long, unlike a password.
3. **HttpOnly**: JavaScript can't read the cookie, so a script injected into the page can't steal it.
4. **Secure**: only sent over HTTPS. Browsers treat `http://localhost` as secure, so it works locally. The tests turn it off because the test client uses plain http.
5. **SameSite=Lax**: the browser doesn't send the cookie on POSTs from other sites, but does send it when following a normal link (like Google's redirect back). Strict would drop it on that redirect.
6. **Origin check** (middleware in `main.py`): every POST, PUT, PATCH, and DELETE must have `Origin` equal to `APP_ORIGIN`, or it gets 403. Browsers always send `Origin` with a POST, and a page can't fake it. This is a second guard next to SameSite. A missing Origin is refused too.
7. **Sign-out** (`POST /auth/logout`) deletes the session row, so even a copied cookie stops working.
8. **`current_user`** is a dependency every user endpoint uses. It hashes the cookie, finds an unexpired session, and returns the user, or 401.

### 6. The Prayers calendar

1. `ensure_prayers_calendar` in `prayers_calendar.py`:
   a) No saved calendar: create "Prayers" in the request's time zone and save its ID.
   b) Saved one exists in Google: reuse it.
   c) Google says 404 or 410 (the user deleted it): create a new one, save the new ID, and mark the old events as pending so they go to the new one.
2. It locks the user's row (`SELECT ... FOR UPDATE`) until it commits, so two requests at the same moment can't both create a calendar.
3. If the database is wiped, the app can't find the old calendar and makes a second "Prayers". I accepted that instead of asking for more access.
4. `google_calendar.py` only has 4 calls: create a calendar, get a calendar, insert an event, update an event. There's no code that could touch another calendar.

### 7. Today's prayers without duplicates

1. **Steps in `POST /prayers/today`**:
   a) Work out "today" in the location's time zone.
   b) Calculate with the milestone 2 calculator. Sunrise is skipped, it's not a prayer.
   c) Save 5 rows in `prayer_events`, all `pending`, and commit. Nothing has gone to Google yet.
   d) Make sure the access token works, then find or create the Prayers calendar.
   e) Send each row to Google. After each one, mark it `synced` and commit.
2. **One row per prayer per day**: the table is unique on `(user_id, local_date, prayer)`. Saving uses `INSERT ... ON CONFLICT DO UPDATE`, so a second run updates the same row, even if two requests run at once.
3. **The row's UUID is the Google event ID**. Google lets apps choose event IDs, using the characters 0-9 and a-v. A UUID in hex (0-9, a-f) fits.
   a) Google refuses a second event with the same ID (409 Conflict).
   b) So if a request times out but Google actually saved the event, the retry gets 409, and the app updates the event instead. No copy.
4. **Insert or update**:
   a) Row already sent to this calendar: update (PUT). If Google says 404, insert it again.
   b) Otherwise insert. On 409, update.
5. **`status: confirmed`** in every update. A user-deleted event stays in Google as "cancelled" with its ID still taken. Updating it with `confirmed` brings it back, so it reappears once, not twice. I couldn't test this against the real Google, so it's in the manual checks. (Since milestone 4, unchanged events aren't sent again, so a deleted event only comes back when it changes. See milestone 4, section 6.)
6. **`extendedProperties.private.appEventId`**: the app's UUID on each Google event. Private properties are only visible to this app. Two-way sync (now a stretch goal) would use it to match Google events back to rows.
7. **Partway failures**: a timeout, 429, or 5xx stops the run. Rows sent so far stay `synced`, the rest stay `pending`, and the answer is 503 with `saved` and `waiting` lists. Running again finishes the job.
8. **Event times**:
   a) Start is the rounded prayer time from the calculator.
   b) End is start plus the block's length (15 minutes back then, see milestone 5 section 23 for now), added in UTC and converted back. Adding in local time could be off by an hour if a clock change fell inside.
   c) Sent to Google as `dateTime` with the offset plus `timeZone`, like `2026-11-01T17:01:00-05:00` and `America/Toronto`.
9. **Description**: where the time came from, like `Calculated (ISNA, standard Asr)`. When a high latitude rule was used, it's added: `Calculated (ISNA, standard Asr, seventh of the night rule)`.

### 8. Tests

1. **`tests/fake_google.py`**: a fake Google that answers the token endpoint and the Calendar API.
   a) It plugs into the app through `httpx2.MockTransport`, so the app's real code runs and only the network is replaced.
   b) It keeps calendars and events in memory and records every request, including whose token was used.
   c) It checks PKCE for real: the verifier has to hash to the challenge.
   d) It can time out, rate limit, fail with 500, "save the event but lose the answer", expire tokens, kill refresh tokens, and delete calendars or events.
   e) Any URL it doesn't know fails the test, so no test can reach the real Google.
2. **`tests/conftest.py`**: fake settings (a new Fernet key each run), the migrations, emptying tables before each test, the fake Google, the clock, and a `sign_in` helper.
3. **`test_auth.py`**: PKCE and S256, only the 3 scopes, wrong or missing state rejected, a flow can't be used twice, HttpOnly cookie with only its hash saved, sign-out, Origin check.
4. **`test_tokens.py`**: tokens stored encrypted, no token ever in a response, expired token refreshed, dead refresh token gives `needs_reauth`.
5. **`test_google_calendar.py`**: each Google error code turns into the right error, timeouts are temporary, 401 refreshes once.
6. **`test_today_prayers.py`**: 5 events with the right times, the right lengths, descriptions, and `appEventId`. Running twice gives 5. Failing on the 3rd event (timeout, 429, 500, 503, lost answer) leaves no duplicates and a rerun finishes. Only the Prayers calendar is ever written. A deleted event comes back once.
7. **`test_prayers_calendar.py`**: created once and reused, recreated after deletion with all 5 prayers.
8. **`test_user_isolation.py`**: two users with two cookies. Neither sees the other's events, and Bob's run only uses Bob's token and calendar.
9. **`test_today_prayers_dst.py`**: Toronto on March 7 and 8 and October 31 and November 1, 2026. Every event has the right offset and lasts exactly its length.
10. **`pytest -m "not database"`** runs only the tests that don't need Postgres. `conftest.py` marks the others automatically.

### 9. How to check it works

1. **Tests**: `pytest` in `backend` with Postgres running. You should see `311 passed`. GitHub Actions runs the same tests with no Google keys.
2. **For real**: follow "Google Calendar" in the README to set up Google Cloud, fill in `.env`, sign in, and run `POST /prayers/today` from `/docs`.
3. **Checks I couldn't automate** (they need the real Google):
   a) Delete one prayer in Google Calendar, run `POST /prayers/today` again, and check it comes back exactly once.
   b) Delete the whole Prayers calendar, run it again, and check a new one appears with all 5 prayers.

## Milestone 4: Setup questions and nightly updates

### 1. Where things are

1. **`web/`**: the website, React and TypeScript, built with Vite.
   a) `src/App.tsx`: picks the screen: sign in, sign in again, setup, or settings.
   b) `src/api.ts`: every call to the backend, and turning errors into messages.
   c) `src/Setup.tsx` and `src/steps/`: the 3 setup questions, one per page. The settings page reuses the same step components for its Edit buttons, plus the methods and Jumuah steps, which aren't in setup for now.
   d) `src/SettingsPage.tsx`: each saved setting on a card with an Edit button, and Sign out.
   e) `nginx.conf` and `Dockerfile`: build the site, then serve it with nginx, which also passes API calls to the backend.
   f) `tests/`: Playwright tests with a mocked API (`mock-api.ts`).
2. **`backend/app/geo/`**: finding places.
   a) `photon.py`: address and masjid suggestions as the user types.
   b) `timezones.py`: location to time zone, offline.
   c) `distance.py`: straight-line distance between two points.
   d) `throttle.py`: spaces out calls to Photon.
3. **`backend/app/user_settings.py`**: reads and saves setup answers, and decrypts the address.
4. **`backend/app/routers/settings.py`**: the setup and settings endpoints.
5. **`backend/app/calendar_window.py`**: works out the next 14 days of events and sends only the ones that changed.
6. **`backend/app/nightly.py`** and **`backend/app/worker.py`**: the nightly job and the worker service that runs it.
7. **`backend/app/http_client.py`**: was `google_http.py`. Renamed because OpenStreetMap calls use it too.
8. **`backend/alembic/versions/0002_settings_masjids_jobs.py`**: the new tables. `0003_drop_overpass_cache.py` drops the Overpass cache (see section 5).
9. **`web/src/SuggestBox.tsx`**: the search box with typing suggestions, used for the location, the masjid, and Jumuah masjids.

### 2. One site: nginx in front of everything

1. **The problem**: the session cookie is `SameSite=Lax`, and the backend refuses any POST whose `Origin` isn't `APP_ORIGIN`. If the website ran on port 5173 and the API on port 8000, they'd be different origins, and every save would get 403.
2. **The fix**: nginx serves the website and passes API calls on, all from `http://localhost:8000`.
   a) `/api/me` goes to the backend as `/me`. The trailing slash in `proxy_pass http://backend:8000/;` strips `/api`.
   b) `/auth/...` goes to the backend unchanged. That's why the Google redirect URI didn't have to change.
   c) Anything else gets `index.html`, the website.
3. The backend isn't published to the host any more. Only nginx is.
4. Uvicorn runs with `--root-path /api`, so `/api/docs` knows its JSON is at `/api/openapi.json`.
5. After sign-in, the callback sends the browser to `/` (the website) instead of `/docs`. A failed sign-in goes to `/?sign_in_error=cancelled` (or `expired`, `state`, `google`). Only these fixed codes go in the URL, and the website turns each into its own message, so nobody can make a link that shows their own text on the sign-in page.
6. Every 401 now has a `reason`: `not_signed_in` shows **Sign in with Google**, and `google_sign_in_expired` shows **Sign in again**, not an error.

### 3. Database

1. **`user_settings`**: one row per user.
   a) The address the user picked and its coordinates are both **encrypted** with the same Fernet key as the Google tokens. Coordinates point to a home just as well as an address does, so they're encrypted too.
   b) The time zone is plain text. The nightly job needs it to know when 3:00 am is.
   c) Each answer is empty until its step is saved. `missing_steps` lists what's left: `address`, `masjid`, and `weekly` (not after **Skip**, which saves "home").
   d) `method` and `asr_method` stay empty until changed on the settings page. Empty means the defaults, ISNA and standard (`method_of` and `asr_method_of`). Jumuah starts with no masjids. Setup doesn't ask about either for now, but the code and anything saved are kept.
2. **`masjids`**: masjids users picked. Ones Photon found on OpenStreetMap have `osm_type` and `osm_id`. Ones picked by their address have `created_by_user_id`.
   a) OpenStreetMap masjids are public, so any user can pick them. One picked by its address is only usable by the user who picked it.
   b) Nothing is made up. A masjid picked by its address has no name, just the address the user picked, so the website asks for a short name. The address of an OpenStreetMap masjid is only what Photon sent. No times are stored yet.
   c) OSM IDs are only unique within a type (a node and a way can share a number), so the unique key is `(osm_type, osm_id)`.
3. **`weekly_masjid_prayers`**: 7 rows per user, one per weekday, each with 5 true/false columns. 0 is Monday, the same as Python's `date.weekday()`.
4. **`user_jumuah_masjids`**: links a user to each Jumuah masjid. A user can have several, or none.
5. **`geocode_cache`** and **`api_throttle`**: see sections 4 and 5.
6. **`nightly_jobs`**: see section 7.
7. **New `prayer_events` columns**: `place` (`home` or `masjid`), `masjid_id`, `summary` (the title), `description`, and `synced_hash`.

### 4. Addresses: Photon

1. **Why Photon**: setup shows suggestions in a dropdown as the user types. Nominatim, OpenStreetMap's main address search, bans that in its usage policy. **Photon** (`photon.komoot.io`) searches the same OpenStreetMap data and is built for search-as-you-type. It's free, and asks apps to be fair.
2. **Being fair to Photon**:
   a) **Wait for a pause**: the website only searches once typing stops for 400 ms. Each keystroke cancels the waiting timer, and also cancels a search already on its way (`AbortController`), so typing "200 Kanata" sends 1 request, not 10.
   b) **At least 3 characters**: fewer gets no search, on the website and again on the backend.
   c) **At most 5 suggestions**: the backend asks Photon for 10 and keeps 5.
   d) **Favour Canada**: Photon is asked to prefer results near the middle of Canada, with a wide radius. Then the backend moves Canadian results to the top, keeping Photon's order otherwise. That's why it asks for 10: a Canadian match in 7th place still makes the top 5.
   e) **Cache**: each answer is kept for 7 days. The same text, with different spacing or capitals, is only sent once.
   f) **Through our backend**: the browser never calls Photon. Every request comes from the backend with the User-Agent `PrayerFit/0.4 (+mailto:<OSM_CONTACT_EMAIL>)`.
   g) **Spaced out**: calls from the whole app are at least 0.25 seconds apart (`throttle.py`).
   h) **Credit**: OpenStreetMap's licence (the ODbL) requires credit wherever its data is shown. One small grey "© OpenStreetMap contributors" link sits in the footer of every page that uses it: setup and the settings page. The landing page shows no OpenStreetMap data, so it has no footer.
   i) **No postal codes**: suggestions and the saved address leave out the postal code. OpenStreetMap's Canadian postal codes are often wrong (it showed the wrong one for my address), and prayer times only need the location. Postal code areas Photon sends as places are dropped too. The cache key got a `v2` so old cached labels with postal codes are never shown.
3. **`throttle.py`**: the last call time lives in one Postgres row.
   a) A caller locks the row (`SELECT ... FOR UPDATE`), waits until enough time has passed, writes the new time, and commits.
   b) Anyone else blocks on the lock until then.
   c) Using Postgres instead of a Python variable means the limit holds across every process.
4. **Picking saves it**: `POST /setup/location/suggest` returns each suggestion with its place in the list. Picking one calls `PUT /settings/location` with the text and that number. The backend reads the answer from the cache, so the saved location is exactly what the user saw, and the browser never sends coordinates.
5. **The dropdown is a combobox**: the input has `role="combobox"` and the list has `role="listbox"`, so screen readers announce it. Up and down arrows move through the list, Enter picks, and Escape closes it.
6. **Keeping the address private**:
   a) It's sent in the request body, never the URL, so it can't show up in access logs.
   b) httpx2 logs every URL at INFO, and a Photon URL contains what was typed. `http_client.py` sets the `httpx2` and `httpcore2` loggers to WARNING.
   c) Error messages never include it. A timeout error from httpx can include the URL, so the app shows its own message instead.
   d) The cache key is an **HMAC** of the text (a hash mixed with the secret key), and the cached answer is encrypted. Without the key, someone can't check a guess like "is 123 Main St in here?" Partly typed addresses are cached too, so this matters even more than before.
   e) `test_address_never_shows_up_in_logs` captures every log line during a full setup and checks the address isn't there. I checked the test works by turning the httpx2 logger back on: it failed.
7. **Failure logs**: when Google or Photon fails, `log_failure` in `http_client.py` writes one line like `Photon failed: status 502 after 0.4 s` or `Google Calendar PUT failed: timeout after 10.0 s`.
   a) The reason is only the status code, "timeout", or "connection error". Never the error's own text, because httpx2 puts the URL in it, and the URL holds the address or location.
   b) Google's 404 and 409 answers aren't logged. The code expects them (a deleted calendar, an event that already exists).
   c) Tests check each kind of failure is logged with its time, and that no address, coordinates, or calendar ID is in the log.

### 5. Time zone and the masjid

1. **Time zone**: `timezonefinder` has the world's time zone borders inside the package, so it works offline and costs nothing. Ottawa gives `America/Toronto`, Regina gives `America/Regina` (no daylight saving).
2. **The masjid is a search box too**: "Which masjid do you usually go to?" works like the location step. Photon is asked for places of worship only (`osm_tag=amenity:place_of_worship`), biased toward the user's saved location.
   a) **Closest first**: the backend asks for 10, works out each one's straight-line distance from home (the haversine formula in `distance.py`), sorts by it, and keeps 5. Each suggestion shows its name and distance, like "Kanata Muslim Association, 1.1 km away".
   b) **Privacy**: Photon gets the home rounded to 2 decimal places (about 1 km), never the exact location. The exact distance is worked out on our server.
   c) **Cached per area**: the cache key includes the rounded home, since "Kanata Masjid" means different places in different cities.
   d) **Same fair use** as the location step: a 400 ms pause, at least 3 characters, at most 5 suggestions, the cache, our User-Agent, and spaced-out calls.
   e) **A masjid not on the map**: if no place of worship matches, or the text has a number in it (house numbers do), addresses near home are added to the list, marked "Address". Picking one saves it with no name, so the website asks for a short name. Most searches stay at one Photon call.
   f) **Photon can't filter by religion**: churches are places of worship too. Since the user types the masjid's name, that's enough to find it. Places of worship with no name are left out, because they can't be told apart. The address search covers them.
   g) **Picking saves it**: `POST /masjids/from-suggestion` reads the same cached search and saves the masjid. One from OpenStreetMap is saved by its `(osm_type, osm_id)`, so 2 users picking KMA share one row. The main masjid and Jumuah masjids both use it.
   h) **Skip**: a small link instead of "I pray at home". It saves "home", so every prayer is at home and the weekly grid is skipped.
3. **What I tried first, and why I took it out**: the first version listed every masjid within 15 km from OpenStreetMap's Overpass service. On my laptop it took 40 seconds one day, and the next day overpass-api.de answered 502 and another public server didn't answer at all. I added backup servers, a background search, and a 30 day cache, but setup still depended on a slow, unreliable service. Photon answers in well under a second, and the user knows their masjid's name, so searching for it is faster for them too. I removed Overpass completely: the code, the cache table (migration `0003`), the `OVERPASS_URLS` setting, and its tests.

### 6. The 14-day window

1. **What it does** (`refresh_calendar`):
   a) Work out each prayer for today plus the next 13 days with the milestone 2 calculator.
   b) Pick home or masjid for each prayer from the weekly grid.
   c) Save each event, then send the ones that changed to Google.
2. **Days, not hours**: the dates are `today + timedelta(days=n)`. Adding days to a date moves the calendar date. On November 1, 2026 (a 25-hour day), adding 24 hours to midnight would land on 11 pm the same day, and a day would repeat. The tests check the window across November 1 and March 8.
3. **Titles**: `Fajr at home` or `Dhuhr at KMA`. (Milestone 5 changed home prayers to just `Fajr`, see section 24 there.)
   a) The masjid part is the short name if there is one, then the OpenStreetMap name, then "the masjid".
   b) The short name is per user, so one person's "KMA" doesn't change anyone else's calendar.
4. **Descriptions**:
   a) Line 1: where the time came from, like `Calculated (ISNA, standard Asr)`.
   b) Masjid events add: "Iqamah times not added yet, so this is the calculated prayer time." Iqamah times come in milestone 5. Until then nothing invents one.
   c) Dhuhr adds why it's after solar noon, with that day's solar noon, like `(12:46:57 pm)`.
5. **Only send what changed** (`synced_hash`):
   a) After Google confirms an event, the app saves a SHA-256 hash of exactly what it sent.
   b) Next time, it builds the event again and hashes it. Same hash means nothing changed, so it isn't sent.
   c) Ticking Asr on Tuesdays sends 2 events, not 70. Saving the same answer twice sends nothing.
6. **Leave the past alone**: a row that already started is skipped, even if the settings changed. It's history.
7. **One update per user at a time**: the website and the nightly job could update the same user at once. `user_lock` takes a Postgres advisory lock (a lock on a number, not a row) for that user.
   a) It's held on its own connection, because the update commits many times, and a normal transaction lock would end at the first commit.
8. **Moving**: if the time zone changes, `ensure_prayers_calendar` PATCHes the calendar's `timeZone`. It's the same calendar, not a new one.
9. **When it runs**:
   a) **Fill my calendar** fills all 14 days, while the user waits (about 10 to 20 seconds with real Google).
   b) Each Edit after setup updates the calendar straight away.
   c) If Google fails partway, the settings are still saved. The website shows "Some prayers haven't reached Google Calendar yet" with **Try again** (`POST /calendar/sync`), and the nightly job retries too.
10. **A trade-off**: in milestone 3, running `POST /prayers/today` again sent all 5 events every time, which also brought back an event the user deleted in Google. Now unchanged events aren't sent, so a deleted event only comes back when its details change. Noticing edits and deletions made in Google is two-way sync, which is now a stretch goal.
11. **`POST /prayers/today`** no longer takes a location. It uses the saved settings and answers 409 "Finish setup first" before setup is done.

### 7. The nightly job

1. **Its own service**: `worker` in Docker Compose runs `python -m app.worker`. Same image as the backend, different command. It checks every 60 seconds.
2. **3:00 am in each user's own time zone**:
   a) A job is due once the user's local clock reads 3:00 or later.
   b) Not 2:00 am: on March 8, 2026, Toronto's clocks jump from 2:00 to 3:00, so 2:00 to 2:59 never happens. 3:00 always does in Toronto.
   c) Comparing the clock reading instead of building a "3:00 am" time also handles places where 3:00 itself is skipped. Helsinki jumps from 3:00 to 4:00, so its job runs at 4:00.
   d) On November 1, 1:30 am happens twice, and both are still before 3:00.
3. **Never twice**:
   a) Each job is saved before it runs, with the ID `nightly:{user_id}:{date}`. Saving it again does nothing (`INSERT ... ON CONFLICT DO NOTHING`).
   b) A worker claims the job with one `UPDATE ... WHERE status = 'pending'`. Postgres only lets one of two workers change that row, so only one runs it. A test starts 2 workers at the same moment.
   c) Even a repeat would be safe: fixed event IDs and the hash check mean nothing is duplicated.
4. **Catching up**: when the worker starts, the first check finds today's job (if it's past 3:00) and runs it.
   a) Only the newest night runs, because it rolls the whole window forward. Older unfinished jobs are marked `skipped`.
   b) A night before the user finished setup is never run. Finishing setup already filled the calendar.
5. **Crashes**: a job still `running` after 15 minutes means its worker died, so it goes back to `pending`.
6. **Expired sign-in**: the job is marked `needs_sign_in` and the worker moves on to the next user. After the user signs in again, the next check runs it. A test has 3 users where the middle one's sign-in expired.
7. **Google errors**: the job is `failed` and tries again 15 minutes later, up to 5 times a night.
8. **One user's bug can't stop everyone**: any other error is caught, logged, and marked `failed`.
9. **Never deletes**: the Calendar client still has no delete call. Past prayers stay in Google.
10. **`run-now`**: runs today's job straight away, using the same job IDs. A second run says "Already ran today". `--force` runs it again, which sends 0 events if nothing changed.

### 8. The website

1. **No router library**: the app only has 4 screens, so `App.tsx` keeps a `view` in React state and switches on it.
2. **Landing page**: the welcome on the left and the sign-in card on the right, using a CSS grid with 2 columns. Below 760 px wide, it's 1 column, so they stack.
3. **One question per page**: `Setup.tsx` keeps which question it's on. It starts at the first unanswered one.
   a) **Back** goes to the previous question with its answer kept.
   b) A saved location shows with a **Next** button, so going back and forward doesn't search again.
   c) After the masjid question, **Skip** skips the grid.
   d) Straight after the last answer, the website calls `POST /setup/finish` and shows "Filling your Prayers calendar…". There's no extra button to press.
   e) **Matches the landing page**: on a computer, a "Setup" heading and the 3 steps (Location, Masjid, Weekly prayers) are on the left, with the current one highlighted (`aria-current="step"`, so screen readers say it too) and finished ones ticked. The question is on the right. On a phone the list is hidden and "Setup · Step X of 3" shows at the top instead. Weekly prayers is crossed out after **Skip**.
   f) **Just the question**: the location page only says "What's your location?". The box still has a label for screen readers, hidden on screen.
4. **Same code for setup and Edit**: each step takes `onSaved`, and a `page` flag that makes its question the page's main heading in setup. The settings page shows the step inside the card being edited.
5. **One search box for everything**: `SuggestBox.tsx` holds the waiting, cancelling, and keyboard code once. The location step, the masjid step (`MasjidSearch.tsx`), and the Jumuah editor all use it.
6. **Short name**: belongs to one masjid, so picking a different masjid clears it. Otherwise "Dhuhr at KMA" would show for Stittsville. Playwright caught this.
7. **Picking a masjid after "I pray at home"** opens the weekly grid straight away, with no Cancel, since the calendar needs it.
8. **Font**: Plus Jakarta Sans, installed from npm (`@fontsource-variable/plus-jakarta-sans`). Vite copies the font files into `dist/assets/`, so our own nginx serves them. Nothing loads from Google Fonts, which would tell Google about every visitor. It's a variable font: one file covers every weight from 200 to 800. Headings use 800 with slightly tighter letter spacing, so they stand out from the 400 body text. A Playwright test checks the font is used and only comes from our own site.
9. **Phones**: one column, tap targets at least 48 px tall. The weekly grid has the 5 prayers as rows and the 7 days as columns, with short day names (Mon, Tue...), so it still fits on a phone without scrolling sideways.
10. **Sign out** posts to `/auth/logout` and goes back to the sign-in screen.

### 9. Tests

1. **`tests/fake_photon.py`**: a fake Photon, like the fake Google. It checks the User-Agent, the bias, and the query, filters by `osm_tag`, and answers places whose words start with what was typed, closest to the bias point first. Any URL it doesn't know fails the test, so no test reaches the real Photon.
2. **`tests/setup_helpers.py`**:
   a) `save_setup` writes a finished setup straight into the database, for tests that only care what happens after setup.
   b) `setup_through_api` answers the 3 questions through the real endpoints, then finishes.
3. **`test_geo.py`**: address suggestions with Canada first, masjid suggestions (places of worship only, closest first, the home rounded to about 1 km, addresses when no masjid matches, cached per area), at most 5, nothing sent under 3 characters, duplicates dropped, the cache, failures with no address in the message, the spacing between calls, time zones for 5 cities, and distances.
4. **`test_settings.py`**:
   a) Each answer saves, and setup is only the 3 questions, with ISNA, standard, and no Jumuah.
   b) The address is encrypted in the raw database row and never logged.
   c) The time zone comes from the location.
   d) Masjid suggestions show name and distance, closest first. Picking one saves it once. A masjid not on the map can be picked by its address.
   e) The weekly grid saves all 7 days.
   f) **Skip** means every prayer at home and no grid. Ticking nothing in the grid means every prayer at home too.
   g) Everything is scoped to one user. Bob can't pick a masjid Alice picked by its address.
5. **`test_calendar_window.py`**:
   a) 70 events with no duplicates.
   b) "at home" and "at KMA" titles.
   c) The iqamah note.
   d) The Dhuhr line.
   e) A change only sends the future events that changed.
   f) Past events stay.
   g) Google failing partway finishes later without duplicates.
   h) The next day adds 5 events and deletes nothing.
6. **`test_window_dst.py`**: the 14-day window across November 1 and March 8. Each day has its 5 prayers, with the right offset, and each event lasts exactly its length.
7. **`test_nightly.py`**:
   a) 3:00 am in each time zone, including both daylight saving days and Helsinki.
   b) Once per user per day, even when started twice or by 2 workers at once.
   c) A crashed job reruns.
   d) A missed night catches up.
   e) One expired sign-in doesn't stop the others.
   f) Retries and the 5-attempt limit.
   g) Fixing times that changed.
   h) `run-now`.
8. **Playwright** (`web/tests/`): the landing page (side by side on a computer, stacked on a phone), "Sign in again", the full setup flow (typing with one search per pause and none under 3 characters, picking a location, searching for a masjid with distances, a short name, the grid with prayers as rows, finish), Back, Change, the arrow keys, Skip, a masjid picked by its address, a failed masjid search, an empty grid, editing the location, the masjid, Jumuah, and other settings, Cancel, and Sign out. Each test runs on a desktop and a Pixel 7 sized screen.
9. **GitHub Actions** runs both: the `backend` job (pytest with Postgres) and the `web` job (type check and Playwright). Neither has any real keys.

### 10. How to check it works

1. **Tests**: `pytest` in `backend` (`432 passed`) and `npx playwright test` in `web` (`60 passed`).
2. **For real**: follow "Go through setup" in the README with your test Google account. The Prayers calendar should have 70 events.
3. **Change a setting**: tick one more prayer on one weekday. The message should say 2 events were sent, and only those 2 change in Google Calendar.
4. **Nightly job**: `docker compose exec worker python -m app.worker run-now --email you@gmail.com`, then again, then with `--force`. Still 70 events.
5. **Checks I couldn't automate** (they need the real services):
   a) The real Photon suggestions for your address and your masjid. Photon can't filter by religion, so typing a masjid's name is what finds it.
   b) That nginx starts and passes `/api` and `/auth` through. I checked the Compose file with `docker compose config` and the `--root-path` setup with uvicorn directly, but there was no Docker engine where I built this.

## Milestone 5: MAWAQIT times, the optional page, drive time, and Jumuah

### 1. Where things are

1. **`backend/app/masjid_times/`**: masjid times from a masjid's own published source.
   a) `source.py`: the small `MasjidTimesSource` interface, `DayTimes`, and the 3 kinds of error.
   b) `mawaqit.py`: the MAWAQIT adapter. Checks links, downloads the page, and reads its data.
   c) `validate.py`: the checks every time has to pass before anything is saved.
   d) `freshness.py`: fresh, stale, or too old.
   e) `store.py`: saves the times per masjid and date, and reads them back for the calendar.
   f) `scheduler.py`: reads each linked masjid at most once every 6 hours.
2. **`backend/app/admin.py`**: `list-masjids`, `link-mawaqit`, `unlink-mawaqit`, `fetch-mawaqit`, and `set-jumuah-length`.
3. **`backend/app/geo/ors.py`** and **`backend/app/drive_times.py`**: drive times from OpenRouteService, saved per user and masjid.
4. **`backend/app/event_plan.py`**: decides which time each prayer uses, writes the descriptions, and adds drive blocks. It's a pure function.
5. **`backend/app/event_times.py`**: the leave and arrival time maths.
6. **`backend/app/jumuah.py`**: the Jumuah picker, also a pure function. **`backend/app/busy_times.py`** reads busy times from Google, and **`backend/app/jumuah_choices.py`** lists the slots the Jumuah question shows.
7. **`backend/app/update_jobs.py`**: calendar updates queued by a settings change or a masjid time change.
8. **`backend/alembic/versions/0004_masjid_times_drive_optional.py`**: the new tables and columns. `0005_main_masjid_for_jumuah.py` adds each existing user's main masjid as their Jumuah masjid (see section 10). It's a separate migration because my laptop had already run 0004, and Alembic never runs a migration twice.
9. **`backend/alembic/versions/0006_jumuah_pick_and_length.py`**: the Jumuah pick, the Jumuah "how early", and each masjid's Jumuah length. It also drops the method columns (see section 16).
10. **`web/src/steps/RequiredPage.tsx`** and **`web/src/steps/OptionalPage.tsx`**: setup's 2 pages. **`web/src/JumuahChooser.tsx`**: the Jumuah question. **`web/src/ColourPicker.tsx`**: the colour dropdown. **`web/src/SettingsEditors.tsx`**: the small editors on Settings.

### 2. Shared masjids

1. Masjids were already shared since milestone 4. A masjid from OpenStreetMap has one row, matched by `(osm_type, osm_id)`, and every user who picks it points at that row. A masjid typed in by address gets its own row for that user.
2. So the times belong to the masjid. KMA's page is read once, and every user at KMA gets the same times.
3. The only change: `user_jumuah_masjids` got a `position`, so the order the user listed their Jumuah masjids is kept. The migration numbers existing ones in name order, the order the settings page already showed.

### 3. Linking a masjid to MAWAQIT

1. There's no website button. I run `python -m app.admin link-mawaqit` on the server. Otherwise any user could link KMA to the wrong page and change everyone's times.
2. **Only the page name is saved.** `slug_from_link` only accepts `https://mawaqit.net` (or `www.mawaqit.net`), drops a language part like `/en/` and a view part like `/m/`, and checks the name is lowercase letters, numbers, and hyphens. `https://mawaqit.net/en/kma-kanata` saves `kma-kanata`.
3. The app builds the URL itself from that name, and the base URL is fixed in the code. So a saved value can never point the server at some other website.
4. Linking a different page deletes the old page's times. Unlinking deletes the times too, and queues an update for every user of that masjid, so their calendar goes back to calculated times.

### 4. Reading a MAWAQIT page

1. **What's on the page**: a MAWAQIT page has the masjid's whole year in a script that starts `confData = {`. `calendar` has 12 months, each mapping a day ("1" to "31") to 6 times: Fajr, sunrise, Dhuhr, Asr, Maghrib, Isha. `iqamaCalendar` has 5 iqamah values per day. `jumua`, `jumua2`, and `jumua3` are the Friday times.
2. **Never run it**: I find `confData =` with a regular expression and read what follows with `json.JSONDecoder().raw_decode`, which reads one JSON value and stops. The page's scripts are never run. If the data isn't plain JSON, the page is rejected.
3. **Limits**: a 10 second timeout, and the page is read in chunks and dropped once it passes 3 MB.
4. **Iqamah in 2 forms**: `"20:15"` is a clock time. `"+10"` means 10 minutes after that day's adhan. An empty value means the masjid didn't publish one, so it stays empty. `iqamaEnabled: false` means no iqamah at all.
5. **Local dates**: I build each date as today plus n days, then look up its month and day. Never "plus 24 hours".
6. **Checks** (`validate.py`): every prayer present, real clock times (`25:00` fails), adhan times in order, iqamah not before adhan, and iqamah at most 90 minutes after. An iqamah that would land after midnight is refused instead of guessed.
7. **One bad value rejects the whole page.** A wrong time means a missed prayer, so I'd rather keep yesterday's good times than save half a broken page. The failure is logged as `MAWAQIT fetch for masjid <id> failed: <reason>`, with the masjid's ID and nothing about any user.
8. **Time zones**: times on the page are clock times in the masjid's time zone, so the database stores them as plain clock times (`time`, not a timestamp). The offset is only added when an event is built, for that exact date. On November 1, 05:30 is 10:30 UTC. On October 31 it's 09:30 UTC.
9. **KMA's real page**: mawaqit.net was blocked in the cloud environment I built this in, so I saved KMA's page (`https://mawaqit.net/en/kma-masjid-ottawa`) from my laptop. Only a trimmed copy is in the repo, `backend/tests/fixtures/mawaqit/kma_page.html`: the `confData` script with just the adhan and iqamah tables, the Jumuah times, and a few labels. The full page stayed out of git, since git keeps deleted files in its history and the repo is public. `test_mawaqit_kma.py` checks times I read off the page by hand, and that all 365 days of 2026 pass the checks.
10. **`+0` means iqamah at the adhan**: KMA's page has `+0` for Asr from Feb 27 to Sep 26 and for Isha from Feb 5 to Oct 14. At first I read it as "not set yet". Then I noticed the dates line up exactly: Isha is `+0` on October 14, when the adhan is after 7:40 pm, and switches to 7:40 pm on October 15, when the adhan is 7:39 pm. Asr does the same at 4:15 pm on September 27. So on those days KMA prays at the adhan. I checked this against KMA's MAWAQIT screen before changing it. Those days are labelled "KMA iqamah (MAWAQIT, ...)" like any other.
11. **`fajrFixationComparedToShuruq`**: the only other setting that could change an iqamah. It ties Fajr to sunrise, but I don't know its format, and KMA leaves it empty. So if a page ever sets it, Fajr's iqamah is treated as not available (Fajr uses the calculated time with the usual note), and the worker logs the page name. Only `null`, empty, and `false` count as off. A `0` counts as set, which needed `value is False` instead of `value in (None, "", False)`, because `0 == False` in Python.
12. **`jumuaAsDuhr`**: when it's true the page has no set Jumuah times, so no slots are read from it.

### 5. Reading each masjid every 6 hours

1. **One job per masjid, not per user.** The job ID is `mawaqit:<masjid id>:<6-hour block>`, like `mawaqit:...:2026-10-25T12`. The blocks start at 00:00, 06:00, 12:00, and 18:00 UTC. The job is saved before it runs, so a second worker or a retry in the same block finds the same row and does nothing. A test has 3 users at KMA and checks MAWAQIT got 1 request.
2. Only masjids that someone uses (as their main or Jumuah masjid) are read.
3. **Backing off**: a 403 or 429 means MAWAQIT doesn't want us right now, so that masjid waits 24 hours (`retry_after`). 3 failures in a row (a timeout, a 500, a broken page) also wait 24 hours. One success resets the count.
4. **What counts as a change**: a saved day whose times are now different, or the very first read. Each read also adds a new date at the far end, but that isn't a change. If it were, every masjid would "change" daily and every user's events would be rewritten every day.
5. **A change queues an update** for every user linked to that masjid (main or Jumuah), and nobody else.

### 6. Freshness

1. Measured from the last read that passed every check.
2. Under 24 hours: fresh. 24 hours to 7 days: stale, still used, and the description adds "MAWAQIT times may be out of date (last updated Oct 22, 2026)". Over 7 days: not used, so calculated times come back. (Milestone 6 changed this to 24 hours in section 16, then back to 7 days in section 32, with a Settings notice instead of a description.)
3. **"updated" in a description is when the times last changed**, not when they were last read. Otherwise the date would move every day and every masjid event would be sent to Google every day for nothing.

### 7. Which time each prayer uses

1. **At the masjid**: the iqamah. With no iqamah that day, or times over 7 days old, the calculated start time, and the description says "Calculated start time (ISNA, standard Asr). KMA's iqamah time isn't available."
2. **At home**: the main masjid's adhan time from MAWAQIT, if it's linked and usable. Otherwise the calculated time, with exactly the same description as milestone 4, so those events don't change and aren't sent again.
3. **Never invent an iqamah.** If it isn't on the page, it isn't in the calendar.
4. `plan_day` gets everything as arguments: the calculated times, each masjid's times and freshness, the drive times, and the busy times. It doesn't touch the database or the network. That made the many cases easy to test.

### 8. Drive time

1. **OpenRouteService** (ORS) is built on OpenStreetMap data and has a free plan (2,000 directions a day, 40 a minute). It gives typical drive times with no live traffic, and the drive block's description says so.
2. **The address**: `https://api.heigit.org/openrouteservice/v2/directions/driving-car`. HeiGIT shut off the old one, `api.openrouteservice.org`, on September 28, 2026. The base URL (`https://api.heigit.org/openrouteservice`) is the default for `ORS_URL` in `config.py`, with no trailing slash, and the adapter adds `/v2/directions/driving-car`. The request itself didn't change: the same POST body and `Authorization` header.
3. **Its own adapter**, like Photon: a 10 second timeout, calls spaced 1.6 seconds apart across the app, and every problem (no key, a timeout, a 429, a server error) returns "don't know". The calendar update carries on without a drive block. "No route found" is a real answer, so it's saved.
4. **The key** goes in the `Authorization` header, never the URL, so it can't end up in a log. It's `ORS_API_KEY` in `.env`. Empty means drive times are off.
5. **Privacy**: only coordinates, rounded to 3 decimal places (about 100 m), are sent. Never an address. The log line only has the service, the reason, and the time it took.
6. **Saved per user and masjid** in `user_drive_times`, with a `route_key`: a keyed hash of the rounded home and masjid points. The points themselves aren't saved again. A drive time is only asked again when there isn't one, the key changed (the user moved, or picked another masjid), or it's over 30 days old. A nightly run for an unchanged user makes no ORS calls.

### 9. Two blocks for each masjid prayer

1. **The maths** (`event_times.py`): target = iqamah (or the calculated start). Arrival = target minus "how early". Leave = arrival minus the drive time, rounded down to the minute. Everything is done in UTC and turned back into local time, so a daylight saving change in between can't add or lose an hour. Example: Isha iqamah 8:15 pm, 5 minutes early, 14 minute drive: the drive block is 7:56 to 8:10 pm, and Isha is 8:15 to 8:30 pm.
2. **Stable IDs**: a drive block's ID is `uuid5(<fixed namespace>, "drive:<prayer event id>")`. The same prayer always gives the same drive ID, so Google refuses a copy (409) the same way it does for prayer events. `prayer_events` got a `kind` column (`prayer` or `drive`), and the unique key is now `(user_id, local_date, prayer, kind)`.
3. **Reminders**: drive blocks get a popup at their start. Prayer blocks still send no reminder settings.
4. **Colours**: `colorId` is added to the event only when a colour is picked. Events from before this milestone hash the same, so they aren't sent again just because the code changed.
5. **The only delete**: when a drive block isn't needed any more (the prayer moved home, or the drive time became unknown), a future one is marked `delete_pending` and then deleted in Google. `delete_drive_block` refuses anything that isn't a drive block or has already started. Prayer blocks and past events are never deleted. If a deleted drive block is needed again, its fixed ID gets a 409 (Google keeps deleted events as "cancelled"), and the update brings it back.

### 10. Jumuah

1. **The picker** (`jumuah.py`) is a pure function. Input: every Jumuah slot from the user's Jumuah masjids for that Friday, the user's pick, the drive time to each masjid, the Jumuah "how early", each masjid's Jumuah length, and busy times. Output: the slot and the reason. Section 17 has the rule.
2. **In the calendar**: on the coming Friday, the Dhuhr row becomes "Jumuah at <masjid>" with its drive block. The Jumuah block is as long as the masjid's Jumuah length, or 45 minutes when it isn't set (section 19). The other prayer blocks have their own lengths (section 23). If the user has Jumuah masjids but none has usable Jumuah times, Dhuhr follows the weekly grid, and the description says Jumuah times aren't available. No Jumuah masjids means a normal Friday.
3. **The main masjid is the first Jumuah masjid** (`follow_main_masjid` in `user_settings.py`), so users don't pick it twice:
   a) Picking a main masjid with no Jumuah masjids yet adds it.
   b) If the Jumuah list is only the old main masjid, a new main masjid takes its place. Choosing "I pray at home" empties it. That way picking a masjid, going Back, and pressing Skip still means no Jumuah.
   c) Any other list was changed by the user, so it's left alone. Saving the same main masjid again does nothing, so a removed one isn't added back.
   d) Migration 0005 does the same for users from before: a main masjid and no Jumuah masjids gets the main masjid. Its downgrade does nothing, since an added row looks the same as one the user picked.

### 11. Update jobs

1. Before, saving a setting updated the calendar right there in the request. Now it queues a job in `update_jobs` first, then runs it in the request, so the website still says "Calendar updated. 3 events sent to Google."
2. **One row per user**, ID `update:<user id>`. Queuing again while it's waiting changes nothing, so 5 masjid changes in a row become 1 update.
3. If it's queued again while it's running, `requested_at` moves past `started_at`, and the job goes back to `pending` when it finishes, so the newer change isn't lost.
4. A Google error leaves the job `failed`, and the worker tries again 15 minutes later, up to 5 times.
5. **The worker** now does 3 things every minute, each with its own `try`: nightly jobs, MAWAQIT reads, then queued updates.

### 12. The optional page

Setup is now 2 pages, so this "step" became page 2 (section 21). The rest of this section still holds.

1. Every answer has a default, and **Skip** saves them. The defaults are 5 minutes early, no short name, and Basil (Google's green, colour ID "10") for both prayer and drive blocks. They're filled in when the page opens, and Skip saves them. They live in one place on each side: `DEFAULT_ARRIVE_EARLY_MINUTES` and `DEFAULT_COLOR_ID` in `user_settings.py`, and `DEFAULT_ARRIVE_EARLY` and `DEFAULT_COLOUR` in `labels.ts`. Users who saved the step before keep what they had: only new answers get the new defaults, and no migration changes old rows.
2. **How early**: a number box, whole numbers from 0 to 60. The website checks it when you press Finish or Save, and shows "Enter a whole number of minutes from 0 to 60." for anything else (61, -1, 2.5, or empty). The form has `noValidate`, so the browser's own bubble doesn't show instead. The backend checks again with `strict=True`, so 2.5, 5.0, or "5" is refused, not rounded.
3. **Nothing reaches Google before this step is done.** Saving the earlier questions never touches Google, because the calendar is only updated once `setup_completed_at` is set, and `POST /setup/finish` refuses to set it until the optional step is answered. The website calls it straight after this step, then sends the user to Google Calendar. `test_nothing_reaches_google_until_setup_finishes` checks that the fake Google got no requests at all until then.
4. **Short name**: moved here from the masjid question. It only shows when there's a main masjid. Picking the same masjid again keeps it, and picking a different one clears it, on the backend now too.
5. **Colours**: Google Calendar has 11 fixed event colours, with IDs "1" to "11" and names like Peacock and Tomato. A normal `<select>` can't show a coloured dot in its options, so `ColourPicker.tsx` is a small listbox: a button that opens a list, with arrow keys, Enter, and Escape. "Calendar colour" (no colour, so the Prayers calendar's own) is still the first choice.
6. `user_settings.optional_saved` says whether the step was answered. The migration sets it to true for everyone who already finished setup, so nobody is sent back to setup.
7. Settings has an editor for each of these on its own (section 22).
8. The footer credits OpenRouteService next to OpenStreetMap.
9. **Like Google's own colour menu**: the colours are in the order Google lists them (Tomato, Flamingo, Tangerine, and so on), each a round dot with Google's name, and the chosen one has a tick. The tick is drawn with CSS (`::after`), so a screen reader reads "Peacock", not "✓ Peacock". `aria-selected` says which one is chosen.

### 13. After setup: Google Calendar in a new tab

1. **The new tab opens inside the click.** Browsers block a new tab that isn't opened straight from a click, so Finish (and Skip) call `window.open` before anything is awaited (`web/src/finishTab.ts`). The tab shows our own `/adding` page: "Adding your prayers to Google Calendar...".
2. **The first tab goes to Settings** straight away and runs the first calendar update there. It's never sent away from our site.
3. **Talking to the new tab**: when the update finishes, the first tab sends the new one `{ type: "open", url }` with `postMessage`, and the new tab goes to `https://calendar.google.com/calendar/r?authuser=<email>` (`web/src/googleCalendar.ts`). The new tab says "ready" once it has loaded and gets the result again, so a fast update can't finish before it's listening. That means the result can arrive twice, so the new tab only acts on the first one. Both sides check the message came from our own site and the right tab, and the new tab only follows a `calendar.google.com` link. It sets `window.opener = null` before leaving, so Google's page can't reach back to ours.
4. **If the browser blocks it anyway**, `window.open` gives nothing back, and Settings shows "Your browser blocked the new tab, so open Google Calendar from here." under the **Open Google Calendar** button.
5. **Finishing without a click** (all answers saved on an earlier visit) can't open a tab, so it just shows Settings with the button.
6. **Why `authuser`**: someone signed in to 2 Google accounts would otherwise land in whichever one is first in the browser, which might not have the Prayers calendar. Google's docs only show `authuser` with a number (the account's place in the browser's list). People report the email works for Calendar too, and an email doesn't change when the list order does. I couldn't test this against the real Google from the cloud environment, so it's a check to do on my laptop with 2 accounts signed in.
7. If the update fails, the new tab shows the error with a link back to Settings, and Settings shows the message and **Try again**. If finishing fails completely (the server didn't answer), both tabs show the error, and **Try again** on Settings finishes setup.
8. **Returning users** land on the Settings page (renamed from "Your prayers"; there was only ever one settings page). It has an **Open Google Calendar** button with the same link, and never redirects on its own.
9. **Tests never open Google**: the mock API catches every `calendar.google.com` URL and answers with a fake page, and records each visit, so a test can check the exact URL.

### 14. Tests

1. **New fakes**: `fake_mawaqit.py` (serves pages, can answer 403, 429, 500, time out, or send 4 MB) and `fake_ors.py` (a drive time per destination, a timeout, a 429, or no route). Both only answer their own host, and any other URL fails the test.
2. **`test_mawaqit_parser.py`** and **`test_mawaqit_links.py`**: adhan, iqamah (clock time and "+10"), Jumuah, missing iqamah, impossible times, a missing day, a changed page format, and links that aren't mawaqit.net.
3. **`test_mawaqit_scheduler.py`**: one fetch per masjid, at most once per 6 hours, 403 and 429 wait 24 hours, 3 failures wait 24 hours, a broken page keeps the last good data, no addresses in the logs, and a change queues updates only for linked users.
4. **`test_freshness.py`**: the 24 hour and 7 day lines.
5. **`test_masjid_times_calendar.py`**: iqamah for masjid prayers, adhan for home prayers, calculated times without a link, stale and too old, daylight saving in spring and fall, a MAWAQIT change sending only the 1 changed event, a broken page sending nothing, and re-running the nightly job sending nothing.
6. **`test_drive_blocks.py`**: the 7:56 to 8:10 example, 0 and 30 minutes early, without iqamah, no drive block at home or without a drive time, stable IDs, popups only on drive blocks, colours on the right blocks, "how early" changing only drive blocks, switching a prayer home deleting only its future drive block, leave times across daylight saving, every event private, and "Commute to" blocks from an earlier version of this branch renamed back in place.
7. **`test_jumuah_picker.py`** and **`test_jumuah_calendar.py`**: the pick, a clashing pick, a pick not on this Friday, every slot clashing, no pick, ties, the window's edges, an unknown drive time, the Jumuah length, the Jumuah "how early", and only the coming Friday getting Jumuah.
8. **`test_busy_times.py`**: free/busy read from the primary calendar only, midnight to midnight on a clock change day, a Google error meaning no busy times, no request without the scope, a busy time moving Jumuah and sending only the Jumuah and its drive block, and zero writes when nothing changed.
9. **`test_jumuah_pick_and_chooser.py`**: the Jumuah pick endpoint, the slots the question shows (start to end with the Jumuah length, the 1st Jumuah pre-selected, a masjid setup hasn't saved yet, no Google or ORS calls), and that there's no commute time setting.
10. **`test_ors.py`**, **`test_optional_settings.py`**, **`test_update_jobs.py`**, **`test_admin.py`**, and **`test_worker.py`** cover the rest.
11. **`test_migrations.py`**: goes back to milestone 4's tables, adds a user with a masjid, a short name, and Jumuah masjids, upgrades, and checks it all survived. Another test does the same from 0005 to 0006 and checks the Jumuah "how early" was copied.
12. **Playwright**: the 2 setup pages with Back, the Jumuah question (last on the Required page, the 1st Jumuah pre-selected, clicking a block, the keyboard, the Jumuah length, skipped at home or with no Jumuah times, a different masjid, a phone screen, and on Settings), Settings as 2 cards with each item edited on its own, the sign-in-again banner and Not now, the optional page filled in and skipped, the colour dropdown with a mouse and with the keyboard (with the tick moving), the Settings page editing how early, the short name, colours, and Jumuah masjids in order, the "Adding your prayers..." message, the new tab that opens Google Calendar (faked), a blocked new tab, both tabs showing the error when the update or the finish fails, returning users landing on Settings with no redirect, the landing page's text and hadith (in light and dark mode), the bigger text size, and the "Adding" page (one line each from 320px to 1280px wide, the week animation in the picked colour, and the spinner when motion is off).

### 15. How to check it works

1. **Tests**: `pytest` in `backend` (`683 passed`) and `npx playwright test` in `web` (`170 passed`).
2. **Google Cloud Console**: in **Google Auth Platform > Data Access**, add `https://www.googleapis.com/auth/calendar.freebusy`. Then sign out and in again, and the banner on Settings goes away.
3. **For real**: get a free ORS key and put it in `.env`. Then follow "Masjid times from MAWAQIT" in the README to link KMA, and run `run-now --force`. In Google Calendar: masjid prayers at KMA's iqamah, home prayers at KMA's adhan, each with its source, a drive block with a reminder before each masjid prayer, Jumuah on the coming Friday if KMA is a Jumuah masjid, every event private, and the colours I picked.
4. **Jumuah and busy times**: pick KMA's 1st Jumuah, then put a test event in my main calendar over it on the coming Friday. Run `run-now --force` and check Jumuah moved to the 2nd in Google Calendar, with "Your pick (1st Jumuah) clashes with your calendar" in its description.
5. **Checks I couldn't do here**: reading KMA's live MAWAQIT page (only the saved copy), a real ORS key, real free/busy answers, and `authuser` with an email on the real Google Calendar. All of those hosts were blocked where I built this.

### 16. Removing the prayer time method

1. Every user now gets ISNA with standard Asr. The Settings card and `PUT /settings/methods` are gone. `DEFAULT_METHOD` and `DEFAULT_ASR_METHOD` in `user_settings.py` are the only place it's set.
2. Migration 0006 drops the `method` and `asr_method` columns. A user who had picked another method moves to ISNA on the next update. Only their future events that changed are sent, since every calculated description names the method. Past events stay as they were.
3. `GET /prayer-times` (milestone 2's calculator) still takes a method, since it's a separate tool and not a user setting.

### 17. The Jumuah pick

1. **What's saved**: a masjid and a slot order (1st, 2nd, or 3rd), not a clock time. MAWAQIT names them `jumua`, `jumua2`, and `jumua3`. A clock time would break the first time the masjid moved its Jumuah, but "the 2nd Jumuah at KMA" still means the same thing.
2. **Each slot's window** is from leaving home to the end of Jumuah: the drive, plus the Jumuah "how early", plus the Jumuah length. A slot fits when its window doesn't overlap any busy time. Ending exactly when a busy time starts still fits.
3. **The rule**, every Friday:
   a) The pick, if it fits: "Your pick (1st Jumuah)."
   b) If it clashes, the earliest Jumuah that fits, across all Jumuah masjids: "Your pick (2nd Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits."
   c) If that slot isn't on this Friday (KMA only has 2 this week), that counts as a clash, with "isn't on this Friday" instead.
   d) If every slot clashes, keep the pick: "Every Jumuah clashes with your calendar. Kept your pick (1st Jumuah)." Milestone 6 changed this to the 1st Jumuah of the day (milestone 6, section 6).
   e) With no pick, the earliest that fits.
4. Ties (2 slots at the same time) go to the masjid the user listed first.
5. **Removing the picked masjid** from the Jumuah list clears the pick, so Settings never shows a pick that can't be used.
6. **Why only the coming Friday**: a MAWAQIT page only shows this week's Jumuah times. So only the coming Friday (today, if it's Friday) gets them. Later Fridays follow the weekly grid for Dhuhr and say "This Friday's Jumuah times aren't published yet, so this follows your weekly prayers." The next read after Friday covers the next one, which counts as a change and queues an update.
7. **The question and the rule are separate.** Setup asks "Generally speaking, which Jumuah would you like to attend?" without a date or busy times (section 22). Busy times only come in every Friday, when the calendar update applies the rule above.

### 18. Busy times from Google (free/busy)

1. **A new scope**, `calendar.freebusy`. It answers "when is this person busy" with start and end times only. No titles, no places, no attendees. That's the least access that lets Jumuah fit around the user's day.
2. **Only the primary calendar.** Google needs a calendar's ID to check it. Listing a user's other calendars would need `calendar.calendarlist.readonly`, which shows their names, so I didn't add it.
3. **The Prayers calendar never counts**: the request only asks for `primary`, and only `primary` is read from the answer. The fake Google answers for the Prayers calendar too (busy all day), and a test checks the app ignores it. Otherwise every Jumuah would clash with its own Dhuhr event.
4. **One call per user per update**, for the coming Friday only, from midnight to the next date's midnight in the user's time zone. Never midnight plus 24 hours, which is wrong on a clock change day.
5. **Nothing is saved.** Busy times are asked for each time they're needed.
6. **Failing safely**: no scope, a dead sign-in, a Google error, or errors for the primary calendar all mean "no busy times". The calendar update carries on as if Friday were free. It's never the reason an update fails.
7. **Users from before** don't have the scope. `GET /me` has `busy_access`, and Settings shows a banner: "Sign in again so Jumuah can fit around your calendar. We only see when you're busy, never what your events are." **Not now** hides it, remembered in `localStorage` in that browser. Storage can be blocked, so it's read in a `try`, and the banner just shows if it fails.

### 19. Jumuah length

1. Each masjid's Jumuah is a different length (khutbah plus prayer), and MAWAQIT doesn't say. So it's set on the server: `python -m app.admin set-jumuah-length --masjid <id> --minutes 40`. Whole minutes from 15 to 90.
2. Without one, it's 45 minutes (`DEFAULT_JUMUAH_MINUTES` in `jumuah.py`), and the description adds "End time is estimated (45 minutes)."
3. The Jumuah block, the Friday rule's window, and the blocks in the Jumuah question all use it. Setting it queues an update for everyone who uses that masjid.

### 20. Drive blocks and private events

1. **Drive times only come from OpenRouteService.** For a while I let each user type their own commute time per masjid, and called the blocks "Commute to KMA". I took both out again before merging: the blocks are "Drive to KMA", and there's no box for your own time. Migration 0006 was changed in place instead of adding a 0007, since my laptop hadn't run it yet.
2. **Renamed, not duplicated**: the event IDs never changed, so any "Commute to KMA" block from that version is updated back to "Drive to KMA" in place. `test_commute_blocks_are_renamed_and_made_private_in_place` checks this, with no inserts at all.
3. **Private events**: every event the app makes has `"visibility": "private"`, so someone the calendar is shared with only sees "busy". Existing future events got it on their next update. Only events that changed are sent, and this changed all of them once.

### 21. Setup on 2 pages

1. **Page 1, Required**: location, main masjid (or **I pray at home**), the weekly grid, and which Jumuah, all on one page and all shown at once. Picking a location saves it right away, since the masjid search sorts by distance from home. **Next** saves the masjid, the grid, and the Jumuah pick.
2. **Page 2, Optional**: short name, both "how early" times, and the prayer and drive colours. **Skip** (top right) saves the defaults. **Finish** saves the answers, then finishes setup.
3. **Back keeps everything**: page 2 stays mounted (just hidden) after the first visit, so its unsaved answers survive going Back. Page 1's answers are already saved by then. If page 1 changes the main masjid, page 2 resets the short name, since it belongs to the old masjid.
4. **Still nothing reaches Google** before Finish or Skip.

### 22. The Jumuah question and Settings

1. **The question**: "Generally speaking, which Jumuah would you like to attend?" It's last on the Required page, after the weekly grid. It's about Fridays in general, so it shows no date and none of the user's busy times.
2. **The view**: a simple midday calendar, from the half hour before the first Jumuah to the half hour after the last one ends. Each slot (1st, 2nd, 3rd) at the user's Jumuah masjids is a block from its start to its end, using the masjid's Jumuah length (45 minutes when it isn't set). This week's times are only the example: the pick is saved by order.
3. **How it's laid out**: a CSS grid with one row per minute, so blocks line up by time. Rows can grow, so when a block's text needs more height (on a phone), every row it covers grows, and everything still lines up. Slots that overlap in time go side by side.
4. **The 1st Jumuah is pre-selected**: the saved pick if there is one, otherwise the 1st slot at the first Jumuah masjid. Clicking a block picks it.
5. **Skipped** when the user prays at home or their masjid has no Jumuah times yet. Then Next saves the 1st Jumuah at their first Jumuah masjid. Someone at home has no Jumuah masjid, so there's nothing to save, and the rule uses the earliest Jumuah that fits if they add one later.
6. **Asking before saving**: on page 1 the masjid isn't saved until Next, so the website sends the masjid IDs it's about to save (`GET /jumuah/slots?masjid_id=...`), following the same "main masjid is the first Jumuah masjid" rule as the backend. It's a GET because it only reads saved MAWAQIT times: no Google, no OpenRouteService.
7. Each block is a real radio button (hidden, with the block as its label), so arrow keys and screen readers work.
8. **Settings has 2 cards** (section 27): **Required** (location, main masjid, weekly prayers, Jumuah pick, with the same view as setup) and **Optional** (Jumuah masjids, short name, both "how early" times, both colours). Each has its own Edit and saves on its own. `PUT /settings/optional` takes every optional answer, so the small editors send the saved answers with just their one change.

### 23. Prayer block lengths

1. Fajr, Asr, and Maghrib blocks are 10 minutes. Dhuhr and Isha are 15, since they're longer prayers. They're in one place: `PRAYER_LENGTHS` in `prayer_sync.py`.
2. Jumuah doesn't use that list. It uses the masjid's own length (section 19).
3. Drive blocks are their own length: from leaving home to arriving.
4. **Existing users**: a block's end time is part of its hash, so the next update sends only the future Fajr, Asr, and Maghrib blocks, now 5 minutes shorter. They keep their IDs, so they're updated in place. Past events and Dhuhr and Isha aren't sent. `test_old_15_minute_blocks_are_shortened_in_place` checks this.
5. The tests write the lengths out themselves instead of importing `PRAYER_LENGTHS`, so a wrong change in the app makes them fail.

### 24. Event titles

1. Prayers at the masjid say where: `Dhuhr at KMA`. Every other prayer is just its name: `Fajr`, not `Fajr at home`. The calendar is already called "Prayers", so "at home" didn't add anything.
2. Drive blocks stay `Drive to KMA`, and Jumuah stays `Jumuah at KMA`.
3. **Renamed, not duplicated**: event IDs don't depend on the title, so the next update changes each future home prayer's title in place. Past events keep their old title. `test_old_at_home_titles_are_renamed_in_place` checks this, with no inserts at all.

### 25. Design: bigger text, wider pages, dark mode, and the landing page

1. **Bigger text**: the base size is 17px on a phone and 18px on a computer, up from the browser's 16px. Almost every size in `styles.css` is in `rem`, so everything grew with that one change.
2. **Wider pages**: Settings and the "Adding your prayers" page went from 600px and 440px wide to 880px and 680px, setup's questions from 620px to 900px, and the landing and setup frames to 1240px. Phones still get a 16px gutter on each side.
3. **Dark mode**: every colour is a token at the top of `styles.css` (`--text`, `--card`, `--field` for text boxes, `--on-green` for text on a green button, and so on). A `prefers-color-scheme: dark` block only changes the tokens, so it follows the phone or computer's setting. I replaced the hard-coded `#fff` backgrounds with `--field` so nothing stays white in dark mode.
4. **The landing page**: a welcome heading, one sentence about what the app does, then the hadith. (Section 34 has the wording it uses now.) The line about only having access to the Prayers calendar is gone.
5. **The hadith stands out**: it's the biggest text on the page, in a serif, in a warm cream block with a gold bar on the left, and its source ("Sahih al-Bukhari 527") is on its own line underneath, smaller and bold. Gold is only used here, so it doesn't look like the rest of the app's green. Dark mode has its own darker gold block with light text.
6. **Why Amiri**: the hadith has the ﷺ sign (U+FDFA), and most fonts, including the one the site uses, don't have it, so it showed as an empty box. Amiri is a free serif with both English letters and ﷺ. It comes from npm (`@fontsource/amiri`) and is served by our own site, like Plus Jakarta Sans. Only the weight I use (400) is loaded, and the browser only downloads the parts of it the page needs.
7. **A bug this caught**: once the location question stayed on screen (section 21), "Saving…" never went away after the location saved, and the address box stayed disabled. It used to disappear after saving, so it never had to reset. It resets now.

### 26. The "Adding your prayers" page

1. **Two lines**: "Adding your prayers to Google Calendar..." and "This can take up to a minute." Each stays on one line (`white-space: nowrap`). So the heading never runs off a phone, its size comes from the screen width: it's about 20 of its own font sizes wide, so the space left after the side padding is divided by 20.5. It tops out at the normal heading size. A test checks every width from 320px to 1280px. On a 320px screen it ends up a little smaller than the line under it, which is the price of keeping it on one line.
2. **The week animation** is CSS only (`.mini-week` in `styles.css`): 7 days across and 5 prayers down. Every block runs the same 7 second `@keyframes` loop, but each starts a little later (`animation-delay` from its turn, `--i`, set in the HTML). So they drop in one by one, day by day, stay, fade in the same order, and start again. Because every block has the same cycle, they stay in step forever. React only draws the blocks. It doesn't run the animation.
3. **The user's prayer colour**: this tab never calls the API, so setup puts the colour in the address when it opens the tab (`/adding?colour=7`). The page only accepts one of Google's 11 colour IDs. Anything else, or "Calendar colour", uses the app's green.
4. **Motion turned off**: a `prefers-reduced-motion: reduce` block hides the week and shows a slow spinner instead.
5. The animation is hidden from screen readers (`aria-hidden`). The heading already says what's happening.
6. Nothing else changed: once the update finishes, the tab still goes to Google Calendar (section 13).

### 27. Frontend polish

1. **The plan**: a calm tool people check every day, so the page stays quiet and the one bold thing is the hadith on the landing page. The colours are 5 tokens at the top of `styles.css`:
   a) Masjid green `#1f5f4a` for buttons and links.
   b) Ink `#17201c` for values and headings.
   c) Muted `#5c6862` for labels and hints.
   d) Paper `#f5f7f6` for the background.
   e) Brass for the hadith block only.
   Plus Jakarta Sans is the text font. Amiri is only for the hadith. Both are served from our own site.
2. **Labels and values never look alike**: a label like "Location" is small, semibold, and muted. The value under it is bigger and darker. A test checks the size and colour.
3. **No all-caps labels**: the setting labels and the hadith source used `text-transform: uppercase`. They're sentence case now. I also took out the middle dots (" · ") between a masjid's name and its distance, in the footer, and in "Setup · Step 1 of 2". The distance is its own smaller line now (`.hint.detail`).
4. **Buttons look clickable**: green with white text, darker on hover, pressed down 1px on click. Secondary buttons have an outline. Every button and link gets a 3px focus ring when reached with the keyboard (`:focus-visible`), so mouse clicks don't show it.
5. **Settings has 2 cards**: Required on the left and Optional on the right from 1000px wide, and Required first on a phone. They don't look the same on purpose: Required is a white card with a shadow, Optional is just an outline, since it's the less important one.
6. **The Jumuah pick** on Settings reads "1st Jumuah at Kanata Muslim Association". "if it fits your calendar" is gone, because the weekly rule (section 22) already handles a clash.
7. **Opening and closing an item**: `Row` in `SettingsPage.tsx` remembers the row's height, and when it switches between showing and editing, it animates from the old height to the new one with the Web Animations API (`el.animate`, 0.22 seconds). The new content fades in with CSS. Only rows the user opened or closed get the fade, so nothing moves on page load. With motion turned off, there's no animation at all, and button transitions are off too.
8. **Colours as swatches**: the saved prayer and drive colours on Settings show their Google colour as a small circle next to the name.
9. **Checked with screenshots** of every page on a computer and a phone, in light and dark mode.

## Milestone 6: Moving prayers around commitments

### 1. Where things are

1. **`backend/app/fit_prayers.py`**: the algorithm. Pure functions, no database and no network, like `plan_day` and `choose_jumuah`.
   a) `prayer_windows`: when each prayer's time starts and ends.
   b) `fit_prayer`: where one prayer goes, given the busy times.
   c) `masjid_is_free`: whether the whole trip to the masjid is free.
2. **`backend/app/event_plan.py`**: `plan_day` now works in 2 passes and uses `fit_prayers.py`.
3. **`backend/app/busy_times.py`**: `busy_between` reads busy times for the whole window in one call.
4. **`backend/app/calendar_window.py`**: keeps moved prayers when free/busy fails, and leaves a masjid prayer alone once its drive has started.
5. **`backend/app/busy_checks.py`**: the 5-minute check for today and tomorrow (every 15 minutes at first, see section 25).
6. **`backend/alembic/versions/0007_prayer_event_fit.py`** adds `prayer_events.fit`. **`0008_busy_check_jobs.py`** adds the `busy_check_jobs` table.

### 2. The main rule: events come first

1. Commitments are the busy times in the user's primary Google Calendar. There's no new screen for typing them in.
2. Anything in the calendar has priority. The prayer works around it.
3. A moved prayer goes in the earliest free time once the prayer's time has started, before or after the event.
   a) Class from 4:00 to 5:00 pm: Asr goes at 5:00.
   b) Isha starts at 7:23 pm and a meeting runs 7:45 to 9:00: Isha goes at 7:23, before the meeting.

### 3. When each prayer's time ends

1. Fajr ends at sunrise. Dhuhr at Asr, Asr at Maghrib, Maghrib at Isha.
2. Isha ends at **midnight**: halfway between Maghrib and the next day's Fajr. Not 12:00 am on the clock, and never the 2 am a "before Fajr" rule would allow.
3. The start times are the same ones home prayers use: the main masjid's MAWAQIT adhan when it's usable, calculated otherwise. That's `_home_time` in `event_plan.py`, which both the events and the windows use, so they can't disagree.
4. **Sunrise** is the calculated one. The MAWAQIT parser reads sunrise but doesn't save it, since it isn't a prayer. The calculated sunrise is rounded down, which is the safe side for an end time.
5. **Midnight is worked out in UTC**, then rounded down to the minute. On October 31, 2026, Maghrib is 6:00 pm (EDT) and the next Fajr is 5:30 am (EST). That's 12.5 real hours, so midnight is 12:15 am. A wall clock would say 11.5 hours and 11:45 pm. `test_isha_midnight_counts_real_hours_on_the_night_the_clocks_go_back` checks this.
6. The last day in the window needs the next day's Fajr, so `plan_window` calculates one extra day, and the masjid times are loaded for it too.

### 4. Prayer lengths

1. The lengths from milestone 5 are now the maximums: Fajr 10, Dhuhr 15, Asr 10, Maghrib 10, Isha 15 (`PRAYER_LENGTHS`).
2. Every prayer needs at least 10 minutes (`MIN_LENGTH`). A shorter gap is skipped.
3. In a gap shorter than the maximum, the prayer shrinks to fit. A 12-minute gap fits Isha as a 12-minute block.
4. A moved prayer has to end by the time its window ends.

### 5. The algorithm

"Normal time" means the iqamah for a masjid prayer and the adhan for every other prayer. A masjid prayer with no iqamah uses its start time.

```
for each prayer, each day:
    if it's a masjid prayer:
        if the drive, the "how early" minutes, and the prayer block are all free:
            pray at the masjid at iqamah, with its drive block
            stop
        else:
            it can't be at the masjid today
    if the normal time is free:
        pray at the normal time
    else if there's a free gap of at least 10 minutes before the prayer's time ends:
        pray in the earliest one, starting no earlier than the prayer's start time
    else:
        keep it at the normal time, flagged as a clash
```

1. **Finding the gap** (`earliest_gap`):
   a) Sort the busy times and join any that overlap.
   b) Start a cursor at the prayer's start.
   c) Walk the busy times in order. The space between the cursor and the next busy start is a gap. If it's at least 10 minutes, use it. If not, move the cursor to the end of that busy time.
   d) After the last busy time, the gap runs to the window's end.
   e) Each prayer only has a handful of busy times, so this is quick: sorting is O(n log n) and the walk is O(n).
2. **Touching isn't overlapping**: a block that ends exactly when an event starts still fits, the same rule Jumuah uses.
3. **2 passes in `plan_day`**:
   a) Pass 1 decides the masjid prayers, using only the user's busy times.
   b) Pass 2 places every other prayer. The normal time check only looks at the user's events. The gap search also avoids the app's own events from pass 1 (drive blocks and masjid prayers) and the prayers already placed. Without that, a moved Asr could land on Maghrib's drive block. `test_a_moved_prayer_never_lands_on_the_apps_own_drive_block` checks it.
   c) Why the app's own events don't count for the normal time: then a home prayer could move just because a masjid drive block touched it, even with an empty calendar.
4. **Never in the past**: the gap search starts at the later of the prayer's start and now, rounded up to the minute. At 7:46 pm, if a meeting turns out to end at 7:45, Isha goes at 7:46, not 7:45.
5. **All the maths is in UTC.** Python compares 2 times in the same `ZoneInfo` by their wall clocks, which is wrong on a daylight saving day. The tests move prayers on November 1 (1:00 am happens twice) and March 8 (2:00 am is skipped).

### 6. Jumuah

1. The user's pick is used if it fits.
2. If it clashes, the earliest Jumuah that fits is used, across all Jumuah masjids.
3. **Changed**: if every Jumuah clashes, the 1st Jumuah of the day is used: the earliest across all Jumuah masjids, with ties going to the masjid listed first. The description says "Every Jumuah clashes with your calendar, so this is the 1st Jumuah." Before, it kept the pick.
4. A Friday without Jumuah times goes through the normal algorithm for Dhuhr.

### 7. Titles and descriptions

1. At the masjid: `Asr at KMA`, as before.
2. Everywhere else: `Asr`, as before.
3. Moved, or a masjid prayer prayed at home because of an event: the title is just the prayer's name. Section 15 has the description.
4. No free time at all: the title is `Asr (clash)`.
5. Drive blocks only exist for prayers actually at the masjid. When a masjid prayer moves, its future drive block is deleted, the same way as when a prayer moves home in the weekly grid.
6. **A prayer that busy times didn't touch keeps exactly the same title as before**, so a check with nothing new sends nothing.

### 8. Saving `fit`

1. Each prayer event now saves `fit`: `normal`, `moved`, or `clash`.
2. It isn't part of what's sent to Google, so it isn't in `event_hash` and never causes a write.
3. It's there for the next section.

### 9. When free/busy fails

1. `BusyTimes.status` is `checked`, `no_access`, or `failed`.
2. **No access** (the user didn't tick free/busy): busy times are empty, so nothing moves. Everything works as it did before.
3. **Failed** (a Google error, a timeout, a bad answer): the busy times are unknown, not empty. If the update treated that as "free", every moved prayer would jump back to its normal time, right into the user's class. So:
   a) The nightly job and settings updates still run, since a new day or a changed setting still needs to go out. But `save_window(keep_moved=True)` leaves every future row with `fit` of `moved` or `clash` exactly as it is, drive block and all.
   b) The 5-minute check stops before saving anything. The next block tries again.
4. A move is never undone because busy times are unknown. `test_a_free_busy_failure_never_undoes_a_move` checks it.

### 10. Events that already started

1. A row that already started is never changed, the same as before.
2. New: a masjid prayer whose drive block has started is left alone too, even though the prayer itself hasn't started. The user is already on the road. Without this, an event added at 7:31 pm would move Isha home while the user is driving to KMA.

### 11. The 5-minute check

1. **Why**: the nightly job runs at 3:00 am. An event added at noon should move that evening's Isha before Isha, not the next night.
2. **What**: every 5 minutes, for each user with setup done, the free/busy scope, and a working sign-in, update today and tomorrow (`refresh_calendar(days=2, busy_check=True)`). Only changed events go to Google.
3. **Stable IDs**: `busy:<user id>:<5-minute block in UTC>`, like `busy:...:2026-10-26T13:05`. The worker runs every minute, but each block's check is saved before it runs (`INSERT ... ON CONFLICT DO NOTHING`) and claimed with one `UPDATE ... WHERE status = 'pending'`, the same pattern as the nightly job. A test starts 2 workers at once and checks free/busy was called once.
4. **Quiet checks are cheap**: when nothing changed, the check returns before even looking up the Prayers calendar. So most checks are 1 free/busy call. Section 25 has the quota numbers. It stays $0.
5. **Cleanup**: check rows older than 2 days are deleted on each run, so the table stays small (288 rows per user per day before cleanup).
6. The worker now runs 4 steps every minute: nightly jobs, MAWAQIT reads, busy checks, then queued updates.
7. The nightly job still covers all 14 days, and asks free/busy for the whole window in one call (from the first day's midnight to the end of the day after the last day, so the last day's Isha is covered).

### 12. The Prayers calendar is never busy

1. Free/busy only asks for `primary`, and only `primary` is read from the answer, the same as milestone 5.
2. The fake Google still answers that the Prayers calendar is busy all day. A test checks nothing moves because of it. Otherwise every prayer would clash with itself.

### 13. Tests

1. **`test_fit_prayers.py`** (pure, no database):
   a) A free normal time stays.
   b) Touching ends don't clash.
   c) Praying before and after an event.
   d) Gaps under 10 minutes skipped.
   e) Shrinking to fit.
   f) Exactly 10 minutes is enough.
   g) A moved prayer fits fully before its time ends.
   h) Clashes.
   i) Joined events.
   j) Avoiding the app's own events.
   k) Never in the past.
   l) Fajr ending at sunrise.
   m) The other windows.
   n) Isha ending at midnight.
   o) Midnight and moving on both daylight saving days.
   p) The masjid trip check.
2. **`test_moving_calendar.py`** (the real calendar update with the fakes):
   a) Scenario 1, Isha at KMA (adhan 7:23 pm, iqamah 7:40 pm, 10 minute drive): a class until 7:35 gives `Isha` at 7:40, and a class from 7:00 to 8:30 gives `Isha` at 8:30.
   b) Scenario 2, Asr at KMA (adhan 3:36 pm, iqamah 4:15 pm, Maghrib 6:01 pm): a class from 3:00 to 6:30 gives `Asr (clash)` at 4:15, and a class from 3:00 to 4:21 gives `Asr` at 4:21.
   c) Isha before a meeting.
   d) The drive block being deleted.
   e) The app's own drive block.
   f) Nothing moving without busy times.
   g) Daylight saving.
   h) Free/busy failing never undoing a move but still applying other changes.
   i) Users without access.
3. **`test_busy_checks.py`**:
   a) A new event moves the prayer, and removing it puts it back on the next check.
   b) Only today and tomorrow.
   c) Nothing changed means zero writes and only a free/busy call.
   d) The Prayers calendar never counts.
   e) A failure changes nothing and the next block retries.
   f) Started events and a started drive aren't moved.
   g) Never in the past.
   h) Who gets checked.
   i) One check per 5 minutes.
   j) 2 workers at once.
   k) Old checks deleted.
4. **Jumuah**: `test_jumuah_picker.py` covers the pick fitting, the pick clashing, and every slot clashing (now the 1st Jumuah). `test_busy_times.py` checks the same through the calendar.
5. I broke the code on purpose to check the new tests fail. I removed the app's own events from the gap search, used wall clock hours for midnight, ignored the drive in the masjid check, turned off `keep_moved`, dropped the started-drive rule, and dropped "never in the past". Each one made at least one test fail.
6. Every old test still passes without changing what it expects, except the Jumuah "every slot clashes" rule, the free/busy call now covering the whole window, and the worker's step list.

### 14. How to check it works

1. **Tests**: `pytest` in `backend` (`753 passed`) and `npx playwright test` in `web` (`222 passed`), with the changes in sections 15 to 24.
2. **For real**, with the test Google account:
   a) Start everything with `docker compose up -d`, so the worker runs.
   b) Add an event to the test account's main calendar that covers one of today's or tomorrow's prayers.
   c) Within 5 minutes, that prayer moves in the Prayers calendar, and its description says something like "Moved because of an event in your calendar (42 minutes after Dhuhr's start time)."
   d) Delete the event. Within 5 minutes, the prayer is back at its normal time.
   e) `SELECT id, status, events_sent FROM busy_check_jobs ORDER BY block_start DESC LIMIT 5` shows the checks.
3. **Checks I couldn't do here**: real free/busy answers from Google. The cloud environment I built this in can't reach Google, so the steps above are the real test.

### 15. Event descriptions: only for moved and clashing prayers

1. **Every other event has no description**, drive blocks included. Before, each one said where its time came from, and drive blocks said the drive time and how early.
2. **Moved**: "Moved because of an event in your calendar (42 minutes after Dhuhr's start time)."
   a) The minutes are from the prayer's start time (the adhan) to where it was placed, worked out in UTC like everything else.
   b) Over an hour it reads "1 hour 12 minutes". Right at the adhan it reads "(at Dhuhr's start time)". `duration_text` and `moved_text` in `event_plan.py` do this, and a test checks 1, 59, 60, 61, 72, 120, and 125 minutes.
   c) A masjid prayer prayed at home at its iqamah counts too, for example "(17 minutes after Isha's start time)".
   d) Jumuah has its own descriptions (section 28).
3. **Clash**: "Your event covers all of Asr's time today, so figure out a way to fit it in." The title stays `Asr (clash)`.
4. **Nothing else, ever.** The app only knows busy times, never event names, so a description can't say what the event is.
5. **Where times come from didn't go away.** It's still saved in `prayer_events.source_description` for every event, and the Settings page shows each masjid's "Times from MAWAQIT, updated Oct 25, 2026". I took the "Calculated times use ISNA with standard Asr." line off Settings later (section 30), since there's no choice to make there. CLAUDE.md's accuracy rule says this now.
6. **Old events lose their descriptions in place.** `google_event` only adds `description` when there is one. An update replaces the whole event (PUT), so leaving the field out removes it from Google. The event body changed, so its hash changed, so every future event is sent once, with the same event ID. Past events keep theirs. `test_old_descriptions_are_removed_in_place` checks this with no inserts at all.

### 16. Masjid times that can't be confirmed

Section 32 changed this again: the last MAWAQIT times are used for up to 7 days, and the notice comes after 24 hours.

1. **24 hours, not 7 days.** `freshness.py` now has just FRESH (under 24 hours), STALE (24 hours or more), and NEVER. Only FRESH is used. A stale masjid's prayers use calculated times until a read works again.
2. **Why that's the safe side**: a calculated start time is never later than the iqamah, so the user turns up early, never late. A week-old iqamah could be wrong after the masjid moved it earlier.
3. **No event description for it.** Instead, Settings shows a notice at the top: "KMA's times couldn't be confirmed since Oct 24, 2026. Your calendar is using calculated times until they're back." (`masjid_notices` on `GET /settings`, from `masjid_notices` in `routers/settings.py`.)
   a) One notice per linked masjid the user uses (main or Jumuah), by the name they see, so the main masjid is "KMA".
   b) The date is the last good read. A masjid that was never read uses the day it was linked, but only once 24 hours have passed, so a masjid linked a minute ago doesn't get a notice before its first read.
4. The /stats page lists the same masjids for me (section 21).

### 17. Masjid search: within 100 km

1. A typo like "Kanta M" used to find churches thousands of km away, since Photon matches loosely and the bias toward home is only a preference.
2. **2 checks**:
   a) Photon gets a `bbox` around the (rounded) home, a little wider than 100 km, so it doesn't even send far away places.
   b) The backend then keeps only places within 100 km by the real (haversine) distance, nearest first. A box has corners further than 100 km, so the box alone isn't enough. A test puts a masjid 105 km away inside the box and checks it's left out.
3. **Addresses only when the text has a number.** Before, no masjid match also searched addresses, so "Kanta M" showed random streets. Now it says "No masjid found near you. Check the spelling, or type the masjid's address instead." Typing "3500 Fallowfield" still finds a masjid that isn't on the map.
4. The cache keys changed (`masjid:100km:` and `near:100km:`), so older cached answers without the limit are never read.

### 18. Light theme only

1. White, black, and green, on a light green page (`--background: #e8f3ea`). The dark mode block is gone and `color-scheme: light`, so the site and the browser's own parts (checkboxes, scrollbars) look the same whatever the device's setting is.
2. **Readable on light green**: I checked each text colour's contrast with a small script. Near-black text is 16:1, the grey-green for labels is 8.9:1, the lightest hint colour is 5.7:1, and white on the green buttons is 7:1. The usual minimum for small text is 4.5:1.
3. The hadith block is now white with a green bar, and notices are white with a green bar (or a dark red bar for a warning).
4. A test checks the page, button, and heading colours are exactly the same with dark mode turned on.

### 19. Layout: nothing covers anything

1. **Suggestion lists push the page down.** They used to be `position: absolute`, floating over the next question, so its text showed through. Now they're part of the page's flow, so the masjid question moves down while the address list is open. The colour picker's list works the same way. A test checks the next heading moves below the open list.
2. **I checked every page with screenshots** at phone (390px), laptop (1280px), and desktop (1680px) widths. That's how I found 3 problems:
   a) In the Jumuah view, the masjid name disappeared from the selected block. Its line hides overflow, and in a flex column that lets it shrink to 0 height first. `flex: none` on each line fixed it.
   b) The Adding page's week ran off the bottom of a laptop screen. The page is now exactly the screen's height and the week fills what's left.
   c) Setup showed the address twice (the "Saved:" panel and the box). See section 20.

### 20. The location box shows the picked address

1. Before, the box still showed what was typed ("139 Escar") after picking. Now `SuggestBox` has `fillOnPick`, so picking puts the suggestion's text in the box.
2. Filling the box would normally start a new search. A `filled` flag stops that until the user types again.
3. In setup, the box starts with the saved address and a "✓ Saved" line under it, instead of a separate "Saved:" panel. Settings still has its panel with Cancel.
4. Suggestion labels never have a postal code (milestone 4), so the box never shows one either.

### 21. The Jumuah question as a Friday

1. A day calendar for Friday: times down the side from 11 AM to 4 PM (wider if a slot starts earlier or ends later), with the rest of the day greyed out (a striped background).
2. **Each slot runs from when to leave home to the end of Jumuah.** `POST /jumuah/slots` now returns `leave_at`: the start minus the Jumuah "how early" minutes and the drive. The top part of the block, from leaving to the start, is lighter and says "Leave 1:11 PM".
   a) It needs the drive time, so it calls `drive_seconds` (OpenRouteService, saved for 30 days like the calendar update). That's why it's a POST now: a GET must never change anything, and this may save a drive time.
   b) With no drive time, the block starts at the arrival time.
3. Blocks are placed by minute: 2px per minute from the view's start. Blocks that overlap go side by side.
4. **Picking**: clicking a block picks it. The picked block is solid green with white text and "✓ Selected". Each block is still a real radio button, so arrow keys and screen readers work.
5. The same component is used in setup and in the Settings editor. In setup it shows as soon as a masjid is picked.
6. **Never skipped silently**: the API now returns `no_times`, the names of Jumuah masjids with no times yet. Setup says "Jumuah times for Kanata Muslim Association aren't available yet. We'll use the 1st Jumuah, and you can change it in Settings later." Settings says the first sentence only.

### 22. The "Adding your prayers" page

1. **Most of the screen**: the page is exactly the screen's height. The heading is 2rem to 3.75rem depending on the screen, and the week fills what's left. "This can take up to a minute." is sized from the screen's width so it always stays on one line (a test checks 320px to 1680px).
2. **Real times**: `POST /calendar/preview` plans this week without saving or sending anything (`preview_week` in `calendar_window.py`). It uses `load_setup(preview=True)`, which only needs the required answers, since the tab opens while setup is still saving the optional ones. If it answers 409, the page asks again, up to 6 times, 1.2 seconds apart, then shows a typical week instead.
3. **The animation**: a week view with times down the side and 7 days across. One block goes in every second, day by day and in time order, so each drive comes just before its prayer. Prayer blocks grow down from their start time, and drive blocks are narrower and slide in from the left, in the drive colour. The day being filled is highlighted, and a caption names the block, like "Adding Thursday's Asr" or "Adding Thursday's drive to KMA". After the whole week it holds for 3 seconds and starts again.
4. React only decides which blocks are shown (a counter that goes up every second). CSS does the movement.
5. **Reduced motion**: a spinner, and the page doesn't even ask for the preview.
6. **Opened by hand**: it now knows there's no setup tab straight away, so it never starts the week or calls the API. A test caught it calling the API before.
7. The tests use Playwright's fake clock (`page.clock`), so "one block a second" and the captions are checked exactly.

### 23. Usage stats

Section 34 simplified this: the /stats page is now total users, a graph of total users per day, and a masjid table, and the daily snapshot table is gone.

1. **Counts only.** `app/stats.py` counts:
   a) Signed up: rows in `users`.
   b) Finished setup.
   c) Active: users with a nightly job, settings update, or 5-minute check that finished "done" in the last 2 days.
   d) New this week: users created in the last 7 days. Not "since Monday", so it doesn't drop to 0 every week.
2. **The command**: `python -m app.admin stats` prints the 4 lines. A test checks nothing in the output has an "@".
3. **A daily snapshot**: the worker's 5th step saves the 4 numbers in `usage_stats` once a day, after 4:00 am Toronto time (after the 3:00 am nightly jobs, so "active" counts last night). The date is the row's ID, so the worker running every minute still saves one row a day. Migration `0009`.
4. **The private page**: `GET /admin/stats` checks the signed-in user's email against `ADMIN_EMAIL`, ignoring capitals. Anyone else, signed in or not, gets exactly FastAPI's normal 404, `{"detail": "Not Found"}`, so it looks like a page that doesn't exist. The website's `/stats` shows "Page not found" for that. Nothing links to it.
5. **The graph**: one SVG line chart, sign-ups and active users over time, on one axis (both are counts of people).
   a) The colours are green and purple. I ran them through a colour-blindness checker, and they pass. Purple is only on this private page.
   b) Each line has its name at its end, so colour isn't the only way to tell them apart.
   c) Hovering snaps a line to the nearest day and shows both numbers.
   d) "Show as a table" has every value.
6. **Masjid times**: every linked masjid whose read is failing or over 24 hours old, with its last good read and the error. Masjid names are public (OpenStreetMap), so this is still nothing about a user.
7. `ADMIN_EMAIL` is in `.env.example` with no value. Empty means nobody can open it.

### 24. Tests for this round

1. **Backend**:
   a) Moved and clash texts.
   b) No descriptions anywhere, and old descriptions removed in place.
   c) The 24-hour rule and the Settings notice.
   d) Masjids within 100 km and the typo case.
   e) `leave_at` and `no_times`.
   f) The week preview.
   g) Stats: the counts, the command, the daily row, the 404s, and the masjid list.
2. **Website**:
   a) The light-only colours, and the suggestion list pushing the page down.
   b) The picked address in the box.
   c) The "No masjid found near you" message.
   d) The Friday view: hours, greyed out, leave times, block positions, and the selected style.
   e) The no-times message in setup and Settings.
   f) The Adding page: size at 6 widths, real times, captions, colours, the loop, the retries, and reduced motion.
   g) The Settings notice.
   h) The /stats page for the admin, someone else, and nobody signed in.

### 25. Checking busy times every 5 minutes

1. `CHECK_EVERY_MINUTES` in `busy_checks.py` went from 15 to 5, so a new event in my calendar moves a prayer within 5 minutes, and deleting it puts the prayer back within 5. The job ID is now the 5-minute block, like `busy:<user id>:2026-10-26T13:05`.
2. **The quota, checked first.** Google's Calendar API docs say:
   a) No charge under 1,000,000 requests a day per project.
   b) 10,000 requests a minute per project.
   c) 600 requests a minute per user.
   d) Full billing details come later in 2026, with at least 90 days' notice.
3. **For 1,000 users**:
   a) Busy checks: 12 an hour, so 288 a day each, and 288,000 a day in all. A quiet check is 1 free/busy call (section 11).
   b) Everything else: the nightly job (1 free/busy call, the calendar lookup, and the new day's events per user), moved prayers, and settings changes. Roughly 20,000 a day.
   c) Total: about 310,000 a day, about 31% of the free 1,000,000.
   d) Per minute: 1,000 checks per 5 minutes is about 200 a minute, far under 10,000. Each user makes about 1 call every 5 minutes, far under 600 a minute.
   e) The free 1,000,000 would run out at around 3,200 users at this rate. Token refreshes go to Google's sign-in server, not the Calendar API, so they don't count.
4. **A limit to know about**: the worker runs the checks one user at a time. If each takes about 0.3 seconds, 1,000 users is about 5 minutes, the whole block. That's fine at today's size, but well before 1,000 users the checks would need to run in parallel (more workers, or a few at a time).
5. Settings says "Updates and changes are reflected on your calendar every 5 minutes." under the email at the top.

### 26. Jumuah is always at the main masjid

1. **No more Jumuah masjids.** The "Jumuah masjids" item on Settings, its editor (`JumuahStep.tsx`), and `PUT /settings/jumuah` are gone. Jumuah at a different masjid is a stretch goal in CLAUDE.md now.
2. **Everything uses the main masjid**:
   a) `Setup.jumuah_masjid` is just the main masjid. `masjid_inputs` builds 1 masjid context, used for both the daily prayers and Jumuah.
   b) `POST /jumuah/slots` takes one `masjid_id` (the main masjid setup hasn't saved yet), or none for the saved main masjid.
   c) Drive times are only asked for the main masjid.
   d) MAWAQIT reads and queued updates only look at main masjids (`users_of_masjid`, `_has_users`).
3. **No Jumuah** when the user prays at home, or the main masjid has no Jumuah times, as before.
4. **The pick follows the main masjid.** `PUT /settings/jumuah-pick` only accepts the main masjid. Saving a new main masjid resets the pick to its 1st Jumuah. Saving the same one keeps the pick. Choosing "I pray at home" clears it.
5. **Migration `0010`** for existing users:
   a) A pick at the main masjid stays.
   b) Any other pick, or no pick, becomes the main masjid's 1st Jumuah.
   c) A user who prays at home has their pick cleared.
   d) The `user_jumuah_masjids` table and the `jumuah_saved` column are dropped, since nothing uses them any more.
   e) Its downgrade puts the table back with each main masjid in it, the way it was before.
   f) `test_migration_0010_keeps_jumuah_at_the_main_masjid` checks all 4 kinds of user.
6. The older migration tests (0004 to 0006) now upgrade only to their own migration before checking, so 0010 dropping the table doesn't break them.
7. `test_main_masjid_jumuah.py` tested the old "main masjid joins the Jumuah list" rule, so I removed it. The pick rules are tested in `test_jumuah_pick_and_chooser.py`.

### 27. Settings: the question, then just the answer

1. Each Settings item now shows its setup question as the label, and only the answer as the value:
   a) "What's your location?"
   b) "Which masjid do you usually go to?"
   c) "Which prayers do you usually pray at the masjid?"
   d) The Jumuah question.
   e) "How early do you want to arrive before iqamah (daily prayers)?" with "5 minutes".
   f) "How early do you want to arrive before Jumuah (Friday prayer)?" with "5 minutes".
2. Short name and the colours never had a question in setup, so they keep their labels.
3. The "Arrive 5 min before iqamah" wording is gone. `minutesText` gives "5 minutes" (or "1 minute").
4. The questions live in one place, `QUESTIONS` in `labels.ts`, so setup, the editors, and Settings can't drift apart.
5. `Row` has a short `title` too, like "How early for prayers". Screen readers and the Edit button use it ("Edit how early for prayers"), since reading out a whole question on every button would be a lot.
6. The Jumuah pick's value is just "2nd Jumuah", since it's always at the main masjid.

### 28. Jumuah descriptions

1. A Jumuah only gets a description when the pick couldn't be used:
   a) The pick clashes: "Your pick (1st Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits."
   b) The pick isn't on this Friday: "Your pick (3rd Jumuah) isn't on this Friday, so this is the earliest Jumuah that fits."
   c) Every Jumuah clashes: "Every Jumuah clashes with your calendar, so this is the 1st Jumuah."
2. A Jumuah at the pick has no description. These are the picker's own reasons (`choose_jumuah`), so the description and the rule can't disagree.
3. This replaced the "Moved because of an event in your calendar (1 hour after Jumuah's start time)" and "covers all of Jumuah's time" texts from section 15.

### 29. How to check it works

1. **Tests**: `pytest` in `backend` (`841 passed`) and `npx playwright test` in `web` (`258 passed`).
2. **For real**, the steps in section 14 now take up to 5 minutes, not 15.

### 30. Small fixes after review

1. **Settings text**: I removed "Calculated times use ISNA with standard Asr." from the Location item. The method can't be changed, so the line didn't help anyone decide anything. "Time zone: America/Toronto" stays, since that one is about the user.
2. **Card colours**: the Required and Optional cards are now the same white, with the same border and shadow, and so is the "Calendar updated. 95 events sent to Google." message above them. Before, Optional was only an outline on purpose (milestone 5, section 27). White reads best on the light green page, and it's `--card` in `styles.css`, the same colour the message already used. One `.settings-card` rule covers both cards now.
3. **Masjids that aren't linked to MAWAQIT**: I link each masjid by hand with `python -m app.admin link-mawaqit`, so I need to know which ones people actually picked.
   a) `unlinked_masjids` in `routers/stats.py` counts users per main masjid, for masjids with no row in `masjid_sources`. Users who pray at home don't count, even if an old masjid is still saved.
   b) Most users first, then by name. A masjid with no name uses its address, then "Unnamed masjid".
   c) /stats shows each one with "3 users" (or "1 user") and its ID, plus the exact `link-mawaqit` command. With none left, it says "Every masjid someone picked is linked."
   d) Finding a masjid's MAWAQIT page automatically is a stretch goal in CLAUDE.md now.
4. **The "Adding your prayers" page**:
   a) Smaller text: the heading is 1.5rem to 2.75rem (it was 2rem to 3.75rem), the line under it is at most 1.25rem, and the caption at most 1.375rem.
   b) A smaller animation: the page is at most 1120px wide (it was 1400px), and there's a little space under the week.
   c) "This can take up to 1 minute.", with a digit.
   d) **A gap between back-to-back blocks**: a drive ends right when its prayer starts, and every block has a smallest height (10px for drives, 16px for prayers) so short ones stay visible. That smallest height could make a drive run into its prayer. Now each block stops 3px (`BLOCK_GAP_PX`) before the next block that day. My first try just cut the block short, but on a phone that squeezed each drive into a thin line. So if cutting it would make it shorter than its smallest height, it keeps that height and moves up a little instead. It's a picture of the week, not the calendar itself, so a drive starting a few pixels early is fine.
   e) This is all CSS `min()`, `max()`, and `calc()` in each block's `top` and `height`, so it works at any screen size without measuring anything in JavaScript.
5. **Tests**:
   a) Backend: `test_masjids_that_arent_linked_yet_are_listed_with_their_user_counts`.
   b) Playwright: the ISNA line is gone and the time zone stays, both cards and the message are white, the unlinked list (and its empty message) on /stats, the "1 minute" text, the smaller font sizes at 6 widths, and a gap of at least 2px between every pair of blocks in a day, with no drive under 9.5px tall, on a laptop and a phone.
   c) The mock preview's drive now ends right when its prayer starts, like the real one, so the gap test checks the hard case.

### 31. Linking masjids to MAWAQIT from my own list

1. **Why a list**: MAWAQIT's search needs a login and it has no sitemap, so the app can't find a masjid's page by itself. I collected Ottawa's 23 MAWAQIT masjids by hand, each with its link and where it is. Users never see any of this.
2. **The file**: `backend/app/data/mawaqit_masjids.csv`, with the columns `name,mawaqit_link,latitude,longitude`.
   a) Most links are share links like `https://mawaqit.net/en/id/9793`. One is a page link, `https://mawaqit.net/en/cio-gatineau`.
   b) `external_id_from_link()` in `mawaqit.py` turns them into what's saved: `id/9793` or `cio-gatineau`. `page_url()` builds the URL again from that, so a saved value can only ever point at mawaqit.net.
   c) "id" is also a language code (Indonesian), so `https://mawaqit.net/id/9793` is a share link but `https://mawaqit.net/id/cio-gatineau` is a page link. There's a test for both.
3. **The ID page is the same page**: I checked a saved copy of `https://mawaqit.net/en/id/9793`. It answers with KMA's page directly, no redirect, and its `confData` has the same times, iqamah, Jumuah, and time zone as KMA's page link. The parser gives the same 7 days from both. So I didn't commit the full page. The trimmed fixture already covers it.
4. **Redirects**: `download()` still follows up to 3 redirects in case MAWAQIT changes this, but by hand, checking each one stays on `https://mawaqit.net`. A redirect anywhere else is refused before it's requested.
5. **Loading the file** (`mawaqit_list.py`):
   a) A new table, `mawaqit_list`, keyed by the saved ID, so loading the file again never adds a copy.
   b) The backend loads it when it starts (FastAPI's `lifespan` in `main.py`), and the worker does too, before its first run.
   c) A fixed name or location in the file replaces the saved one. A row removed from the file stays, since users may be linked to it.
   d) It's a file loaded on start, not a migration, so adding a masjid is one new line, not a new migration.
   e) One bad line stops the load, and the message names the line, like `mawaqit_masjids.csv line 5: the name is empty`. On start that's logged, not raised, so a typo can't take the site down. A test reads the real file on every push, so a typo fails CI first.
6. **Matching** (`match.py`), plain functions with no database:
   a) Within 100 m: a match, even with a different name. Map names are often spelled differently ("MAC QIC"), but 2 masjids are almost never within 100 m of each other.
   b) From 100 m to 200 m: a match only if the names closely match. `name_words()` drops accents, punctuation, and common words (masjid, mosque, association, centre, center, Ottawa, the, of). Then the names match if one's words contain the other's, or if they're at least 85% alike (`difflib`). "Ottawa Main Mosque (OMA)" gives {main, oma}, which contains "Ottawa Main Mosque" ({main}). "Jami Omar" and "Jamia Omar" are 95% alike.
   c) Exactly 1 match links. 0 is "no match", and 2 or more is "unclear", so the app never guesses between 2 masjids.
7. **When it links** (`auto_link.py`):
   a) In setup, when a user picks a masjid (`POST /masjids/from-suggestion`). `link_and_fetch` links it and reads its page straight away, so the Jumuah question already has the real Jumuah times. It uses the worker's job ID for this 6-hour block, so picking again never reads MAWAQIT twice. Any error is logged and dropped, so MAWAQIT being down never stops setup.
   b) When the list changes (the file has new or changed rows on start, or `add-mawaqit`). `rematch_picked` matches every masjid users picked that isn't linked. The worker reads the new links within a minute, and that updates their calendars.
8. **My links come first**:
   a) `masjid_sources.origin` is "admin" (`link-mawaqit`) or "auto". Migration 0011 marks every link made before this as "admin".
   b) Automatic matching only looks at masjids with no link, so it never replaces one of mine. `link-mawaqit` does replace an automatic one.
   c) `unlink-mawaqit` sets `masjids.no_auto_link`, so a wrong automatic link I remove after a spot-check doesn't come back. `link-mawaqit` clears it.
   d) Automatic links also save which list entry they matched and how far away it is, for /stats.
9. **Admin commands**:
   a) `add-mawaqit <link> --name --lat --lon` saves a list row straight away and links matching masjids. It says to add the same line to the CSV, since the CSV is what rebuilds the list.
   b) `scan-area` asks OpenStreetMap's Overpass API for every masjid within 40 km of Ottawa and prints each as linked, no match, or unclear, then the totals. It only reports. Overpass is free, and only this command uses it. Setup still searches with Photon, since Overpass is meant for occasional big queries, not one per user. `--km` is limited to 100.
10. **/stats**:
    a) "Linked automatically": the masjid's map name, the list name it matched, the MAWAQIT link, the distance, and how many users. Newest first, including links nobody has saved yet (0 users), so I can spot-check every one.
    b) "Masjids with no MAWAQIT match" replaced section 30's "not linked" list. It gives a reason, worked out again from the list each time: "No listed masjid within 200 m", "2 listed masjids are close, so it wasn't linked", or "Unlinked by hand".
    c) A masjid picked by its address now shows "(no name, picked by address)". Section 30's list showed the address, which is where one user said their masjid is, so that was a privacy slip. `list-masjids` already hid it.
11. **Tests**:
    a) `test_masjid_match.py`: a match within 100 m with a different name, a name match at 150 m, a different name at 150 m, 2 close masjids (no link), too far (no link), the 100 m and 200 m edges, and name matching.
    b) `test_mawaqit_list.py`: the real file (23 rows, valid links), each masjid loading once, the app loading it on start, a fixed row, bad lines, and a list change linking a masjid a user already picked.
    c) `test_auto_link.py`: setup links KMA and reads `/en/id/9793` once, so the Jumuah question has its 1:15 Jumuah; MAWAQIT being down; a manual link never replaced (by setup, a list change, or `add-mawaqit`); an unlinked masjid not linked again; `add-mawaqit`; and `scan-area` with a fake Overpass.
    d) `test_mawaqit_download.py`: share links and page links, redirects within mawaqit.net, and redirects anywhere else refused.
    e) A migration test for 0011, and Playwright tests for both new /stats lists.
12. **Counts**: `pytest` in `backend` gave `830 passed`, and `npx playwright test` in `web` gives `230 passed`.

### 32. Keeping MAWAQIT times for up to 7 days

1. **What changed**: section 16 switched to calculated times 24 hours after the last good read. Now the last MAWAQIT times are kept for up to 7 days.
2. **Why**: each read saves a full 30-day calendar (`FETCH_DAYS = 30` in `scheduler.py`), with every day's adhan and iqamah. If MAWAQIT blocks us for a few days, the times we already have are still the masjid's own published times, and much closer to right than calculated ones.
3. **The steps** (`freshness.py`), measured from the last good read:
   a) Under 24 hours (`FRESH`): used.
   b) 24 hours to 7 days (`STALE`): still used. Settings shows a notice.
   c) Over 7 days (`TOO_OLD`): not used, so calculated times are used until a read works again.
   d) Never read (`NEVER`): calculated times.
   `Freshness.usable` is True for the first 2, and everything that picks a time goes through it (`MasjidTimes.usable_day` in `store.py`), so this was a one-file logic change.
4. **The Settings notice** (`masjid_notices` in `routers/settings.py`) still starts after 24 hours, with 2 versions:
   a) Still used: "KMA's times couldn't be confirmed since Oct 22, 2026. Your calendar is still using the last times read from MAWAQIT, and switches to calculated times on Oct 29, 2026 if they still can't be read." The switch date is the last good read plus 7 days, in the user's time zone.
   b) Over 7 days, or never read for a day: "KMA's times couldn't be confirmed since Oct 15, 2026. Your calendar is using calculated times until they're back."
5. **The line under the masjid** says "so the last times read are used" or "so calculated times are used" to match.
6. **When the switch shows up**: nothing runs at the 7-day mark itself. For users who allowed free/busy, the next 5-minute check updates today and tomorrow. Every other day, and every other user, gets it from the nightly job.
7. **Tests**:
   a) `test_freshness.py`: still used at exactly 24 hours and exactly 7 days, and not used at 7 days and 1 second.
   b) `test_masjid_times_calendar.py`: a read 7 days ago still gives Isha at KMA's 8:15 pm iqamah, and a read 7 days and 1 minute ago gives the calculated start.
   c) `test_optional_settings.py`: both notice texts, the switch date, and both masjid lines.
8. **Counts**: `pytest` in `backend` gives `832 passed`, and `npx playwright test` in `web` gave `230 passed` (238 after section 33).

### 33. The hadith highlight and a simpler Jumuah question

1. **"praying on time"** on the landing page is bold, with a soft gold highlight (`--gold-soft`, `#f6e2a6`).
   a) It's a band behind the lower part of the words, like a highlighter pen (a `linear-gradient` background), not a box. Amiri's lines are tall, so a full box looked heavy.
   b) The near-black text on the gold is 14.5:1.
   c) It has `white-space: nowrap`, so the phrase is never split across 2 lines on a phone.
2. **The Jumuah question** (`JumuahChooser.tsx`), on setup and Settings:
   a) Shorter: 1.2px a minute instead of 2, so 11 AM to 4 PM is 360px tall instead of 600. The width is the same.
   b) Each block covers just the Jumuah, from its start to its end. The "Leave 1:11 PM" part and the hint about it are gone. The API still sends `leave_at`, since the calendar's drive blocks use it.
   c) All the blocks are in 1 column. `place()` puts each one at its time, but never shorter than 54px (`MIN_BLOCK_PX`), so its 2 lines always fit. If that would make it reach the next block, the next one moves down to keep a 6px gap (`GAP_PX`), and the day grows if a block moves past 4 PM.
   d) Inside a block: "1st Jumuah" and "1:30 to 2:15 PM". No masjid name, since Jumuah is always at the main masjid.
   e) The picked block is a light green (`--green-light`, `#b9e0c4`) with dark green text (7.1:1), and a small ✓ right after "1st Jumuah" instead of the word "Selected". The ✓ is hidden from screen readers, since the radio button already says it's picked.
3. **Tests**:
   a) The hint is exactly "This week's Friday, as an example."
   b) A block starts at 1:30 and is 45 minutes tall, with no "Leave" and no masjid name.
   c) 11 AM to 4 PM is 360px.
   d) 3 Jumuahs only 20 minutes apart stay in 1 column with at least a 4px gap, and nothing in any block is cut off, on setup and on Settings.
   e) The picked block's colours and tick.
   f) The gold highlight on "praying on time".
4. **Counts**: `npx playwright test` in `web` gives `238 passed`.

### 34. A simpler /stats page, and the new name: PrayerFit

1. **/stats has 3 parts now**:
   a) "Total users: 42" at the top.
   b) A graph of total users over time, one dot per day. Hover over a dot, tap it, or tab to it, and a box shows the date, how many signed up that day, and the total so far.
   c) A table of each masjid with how many users picked it, most first, with a small "No MAWAQIT times" tag on the ones that aren't linked. Masjids with 0 users aren't there, and a masjid picked by address shows as "(picked by address)", never the address.
   d) Gone: finished setup, active, new this week, the graph's second line and table, "Linked automatically", the no-match list, and the masjid times list.
2. **The graph comes from sign-up dates** (`daily_totals` in `app/stats.py`):
   a) It counts users by the local date of `users.created_at` in Toronto time (Postgres `timezone()`), then adds them up day by day, with a point for every day from the first sign-up to today, even days with 0.
   b) So nothing needs saving each day. The worker's "usage stats" step and the `usage_stats` table are gone (migration 0012 drops it).
   c) Next day means the next calendar date, never "plus 24 hours", like everywhere else.
3. **The labels that overlapped**: the graph used to be drawn 640 wide and shrunk to fit a phone, so 12px text became about 7px and the "0" and the first date ran into each other.
   a) Now it's drawn at its real width (a `ResizeObserver` measures the box), so text is 12px on every screen.
   b) The dates sit 30px below the bottom line, well clear of the "0".
   c) The last date is left out if it would be under 96px from the first.
   d) The box opens inward at the edges, and below or above the dot, so it never covers the dot it's about.
   e) A tap fires "pointer leave" when the finger lifts, so only a mouse leaving hides the box.
4. **`python -m app.admin stats`** prints the same: "Total users: 42", then each masjid and its count, with "(no MAWAQIT times)" where it applies. Both use the same functions, `total_users` and `masjid_counts`.
5. **The rename to PrayerFit**: the landing page now says "Welcome to PrayerFit" and "PrayerFit puts your daily prayers and your masjid's times in your Google Calendar, planned around your day.", with the hadith under it. The name also changed in:
   a) the browser tab title (`web/index.html`)
   b) `package.json`
   c) the FastAPI title ("PrayerFit API")
   d) the User-Agent sent to Photon, MAWAQIT, and Overpass (`PrayerFit/0.4`)
   e) the README, CLAUDE.md, this file, and the product description, now `PrayerFit_App.md`
6. **What didn't change**:
   a) The Google calendar the app makes is still called "Prayers".
   b) The GitHub repo kept its name until this PR was merged. Section 36 renamed the Docker project, the volume, and the database user and name too.
   c) The app name on Google's sign-in screen comes from my Google Cloud project's settings, so I change that in the Google Cloud console. The README says where.
7. **Tests**:
   a) Backend: total users, the daily points (including a sign-up at 10:30 pm in Ottawa that's already the next day in UTC, and days with 0), the masjid counts (home users and masjids with 0 users left out, the address never shown), the command's output, and that the snapshot table is gone.
   b) Playwright: only the 3 parts, a dot per day, hover, tap, and keyboard, no labels overlapping and 12px text on a phone, the box staying inside the graph and off its dot, the table with its tags, and the empty states. Also the new landing page text and the tab title.
8. **Counts**: `pytest` in `backend` gives `831 passed`, and `npx playwright test` in `web` gives `246 passed`.

### 35. Delete my account

1. **Where**: the very bottom of Settings, under Sign out. It's outlined in red (`button.danger-outline`), not filled, so it looks careful rather than inviting.
2. **It asks first**: "This deletes your PrayerFit account, your settings, and the Prayers calendar from your Google Calendar. This can't be undone." The confirm button is solid red. Cancel gets focus, so a stray Enter deletes nothing. It's an `alertdialog` inside the page, not a pop-up window, so it works the same on a phone.
3. **`DELETE /account`** (`app/account.py`), in order:
   a) Delete the app's "Prayers" calendar (`DELETE /calendars/{id}`), so every event goes with it. That's the only call into their Google Calendar. The `calendar.app.created` scope can't reach anything else anyway.
   b) Revoke the app's access (`POST https://oauth2.googleapis.com/revoke` with the refresh token). That also ends every access token. Google answering "already revoked" counts as done.
   c) Delete the user row. Every table with their data points at `users.id` with `ON DELETE CASCADE`, so Postgres deletes the rest in the same step: sessions (every browser they're signed in on), Google tokens, settings, weekly prayers, the calendar row, prayer events, drive times, and every job.
   d) Masjids they typed in by address have `created_by_user_id`, so they go too, with their MAWAQIT link and saved times. Only the person who typed one in can pick it (`usable_masjid`), so no other user can be using it. Masjids from OpenStreetMap are public and stay.
   e) The answer clears the session cookie, and the website shows the landing page with "Your account has been deleted."
4. **When Google can't help**: if Google can't be reached, or their sign-in had expired, steps a and b are skipped and everything stored is still deleted. The answer says `{"google_cleaned": false}`, and the landing page adds that they can delete the "Prayers" calendar in Google Calendar themselves. A calendar they already deleted counts as done.
5. **No races**: it holds the same per-user lock as calendar updates (`user_lock`), so a 5-minute check or the nightly job can't write to the calendar halfway through.
6. **Not linked to them, so not deleted**: Photon search answers are cached for 7 days, keyed by a keyed hash of the search text and encrypted (`geocode_cache`). Nothing in a cache row says who searched, so it can't be found by user. It expires on its own after 7 days.
7. **Tests** (`test_delete_account.py`):
   a) Nothing about the user is left in any table. The test checks every table's ID columns for their ID, and every text column for their ID inside it, like a job ID. A 2nd user's rows are all still there.
   b) Exactly 1 Calendar API call: deleting their Prayers calendar. Their access is revoked. The 2nd user's calendar and access are untouched.
   c) Signed out in every browser.
   d) A typed-in masjid goes, with its MAWAQIT link and times. KMA stays.
   e) Google unreachable, and an expired sign-in: everything stored is still deleted, and the answer says `google_cleaned: false`.
   f) It needs sign-in, and another site can't do it (the Origin check).
   g) Playwright: the red outline, the question, Cancel, the landing message, the Google-unreachable message, and an error keeping them on Settings.

### 36. The /stats box, and PrayerFit everywhere

1. **The /stats box** now works like YouTube's:
   a) It shows only while the mouse is over a dot, and moving off hides it. The rest of the graph shows nothing.
   b) Each dot sits in a `g.dot-target` with an invisible 12px circle around it, so it's easy to point at.
   c) On a phone there's no hover, so tapping a dot shows it. Tapping anywhere else hides it: while the box is up, a `pointerdown` listener on the page hides it unless the tap was on a dot. Lifting the finger fires "pointer leave", which is ignored for touch.
   d) Keyboard focus still shows it, and Tab moves to the next day.
2. **The last of the old name**:
   a) `docker-compose.yml` has `name: prayerfit`. Docker named the project after the folder before, so the containers and the volume are now `prayerfit-*` and `prayerfit_db-data` wherever it's cloned.
   b) The database user and name in `.env.example` are `prayerfit`.
   c) The README's commands use `prayerfit`, and the clone link is `https://github.com/hakeemkashif-34/prayerfit`.
   d) Searching the repo for the old name, in any capitalization and with a space, `_`, or `-`, finds only the README's 3 lines about removing the old Docker volume, which need its old name. Masjid names like Kanata Muslim Association stay as they are, and the Google calendar is still called "Prayers".
3. **Moving to the new names**: a fresh database starts in `prayerfit_db-data`. The README says which 3 `.env` lines to change and how to remove the old volume.
4. **Counts**: `pytest` in `backend` gives `841 passed`, and `npx playwright test` in `web` gives `258 passed`.

### 37. The landing sentence and a fuller highlight

1. **The sentence** under "Welcome to PrayerFit" is now "An app that syncs your daily prayers and masjid times to your Google Calendar, based on your location and planned around your day."
2. **The "praying on time" highlight** replaced section 33's highlighter band:
   a) A solid gold, `--gold-highlight` (`#fbe08a`), a little brighter than before but still soft. The /stats tag keeps the old `--gold-soft`.
   b) It covers the whole height of the words. Amiri's line box is about 1.75 times the font size, with lots of empty room above and below the letters, so a plain background made a tall box with big gaps. As an `inline-block` with `line-height: 1`, the box is just the words, and padding of 0.07em on top and 0.09em at the bottom puts about the same space above and below the letters (I measured 5 to 7px each way in screenshots).
   c) Slightly rounded corners (0.22em), and a little more padding at the sides.
   d) It moves to the next line as a whole, so on a phone it's never split across 2 lines. At 320px wide it still fits.

## Milestone 7: Deploy

### 1. Where things are

| File | What it does |
|---|---|
| `docker-compose.prod.yml` | The server's changes on top of `docker-compose.yml` |
| `deploy/Caddyfile` | HTTPS and the redirect to the main address |
| `deploy/production.env.example` | The server's `.env`, placeholders only |
| `deploy/server-setup.sh` | Run once on a fresh Ubuntu VM |
| `deploy/backup.sh` | The daily database backup |
| `deploy/update.sh` | Puts the latest `main` on the server |
| `web/src/PrivacyPage.tsx` | The privacy policy at `/privacy` |

The README's "Deploy" section has every step in the Azure portal, on the server, and in Google Cloud Console, in order.

### 2. Why one Linux VM

1. **Cost**: Azure's free services include 750 hours a month of a B2pts v2 VM (Arm64, 2 vCPUs, 1 GB RAM) and a 64 GB P6 SSD. 750 hours covers a whole month of 1 VM. The only thing that uses credit is the static public IPv4 address, about $3 to $4 a month, so about $45 of the $100 over 12 months.
2. **Same as my laptop**: it runs the exact same `docker-compose.yml`. Container Apps and App Service would each need the app split into separate pieces, a managed Postgres (free for 12 months, then paid), and a different way to run the worker.
3. **Skills**: a VM means I do the Linux work myself (SSH keys, a firewall, cron, swap, security updates) on top of the Cloud parts (the VM, network rules, a static IP, a DNS name, a budget).
4. **Why Arm64**: I planned on B2ats v2 (x86, like my laptop). My Azure for Students subscription only allows 5 regions (`belgiumcentral`, `denmarkeast`, `canadacentral`, `germanywestcentral`, `norwayeast`), and in Canada Central both B2ats v2 and B1s said "NotAvailableForSubscription". B2pts v2 is the Arm64 free size, and it was available. It needs security type **Standard**, since it doesn't support Trusted launch, and the Arm64 Ubuntu image.
5. **The catch**: if the VM dies, the site is down until I fix it, and I'm the one who installs updates (automatically, below). For a student project with a few users that's fine.

### 3. Running on Arm64

The server's CPU is Arm64, my laptop's is x86. Programs built for one don't run on the other, so I checked every piece:

1. **Images**: Postgres 17, `python:3.13-slim`, `node:22-alpine`, `nginx:1.29-alpine`, and `caddy:2.10-alpine` are all "multi-arch". Each tag holds a version per CPU, and Docker pulls the one that matches. I checked with `docker buildx imagetools inspect`, which listed `linux/arm64/v8` for all 5.
2. **Python packages**: most packages with C code ship ready-made "wheels" per CPU. I asked pip to download every package for Arm64 Linux and Python 3.13 (`pip download --platform manylinux2014_aarch64 --only-binary=:all:`), and all of them had one except `timezonefinder` 9.2.0, which only has x86 wheels.
3. **timezonefinder**: without a wheel, pip builds it from its source. Its C part needs a compiler, which `python:3.13-slim` doesn't have, but its `setup.py` catches that error and installs the pure-Python version. To test that path on my x86 machine, I built the backend image with `PIP_NO_BINARY=timezonefinder`, which forces the same source build. It installed with no C files, found the right zones for Ottawa, Vancouver, Halifax, and Regina, and all 437 backend tests that don't need Postgres passed in that image.
4. **Website build**: Vite uses 2 native tools, Rolldown and Lightning CSS. `package-lock.json` has their `linux-arm64-musl` versions (musl is the C library Alpine uses), so `npm ci` installs the right ones.
5. **server-setup.sh**: Docker's Ubuntu repo has Arm64 packages, and the script already asks `dpkg --print-architecture` which one to use. Everything else in it (swap, ufw, SSH, updates, cron) doesn't depend on the CPU.

### 4. HTTPS with Caddy

1. Google only allows `https://` redirect URIs (except localhost), and the session cookie is `Secure`, so the site needs HTTPS.
2. Caddy is a web server that gets a free certificate from Let's Encrypt by itself. When it starts, Let's Encrypt checks that the name really points at this server (it asks for a file over port 80), then gives a certificate that lasts 90 days. Caddy renews it about 30 days before it runs out. No cron job, no certbot.
3. It also sends every `http://` visit to `https://`.
4. Caddy only passes requests to `web` (nginx), which is unchanged from my laptop. So the order is: browser, Caddy (HTTPS), nginx (website and `/api`), backend.
5. The certificates are saved in the `caddy-data` volume. Without it, every restart would ask Let's Encrypt again, and it only gives 5 certificates for the same names a week.
6. **The redirect to the main address**: `SITE_ADDRESS` can list several names. Any request whose `scheme://host` isn't `APP_ORIGIN` gets a 308 redirect there. That matters after the switch to prayerfit.me: the session cookie only belongs to one address, and the backend refuses POSTs whose `Origin` isn't `APP_ORIGIN`, so the old Azure address would half work without it. I tested both cases with curl: the main address went through, another name got `308` to the main one with the same path.

### 5. The production Compose file

`docker compose -f docker-compose.yml -f docker-compose.prod.yml` merges the 2 files. The second one only lists what's different:

1. `restart: unless-stopped` on every service. After a crash or a reboot (for example, a kernel update at 4:30 am), Docker starts them again. `unless-stopped` means a service I stopped on purpose stays stopped.
2. `ports: !reset []` on `db` and `web`. On my laptop, `db` publishes 5432 so tests can reach it, and `web` publishes 8000. A normal override can only add ports, not remove them, so `!reset` clears the list. This is important: Docker writes its own firewall rules for published ports, and they go around ufw. If 5432 were published, Postgres would be open to the internet even with ufw on. Only Caddy publishes ports now, and `docker compose ps` shows `5432/tcp` with no `0.0.0.0` in front.
3. Log limits: 3 files of 10 MB per service. Docker keeps logs forever by default, which would fill the disk slowly.
4. `SITE_ADDRESS` and `APP_ORIGIN` use `${...:?message}`, so Compose stops with a clear error if `.env` is missing them instead of starting Caddy with a blank address.

### 6. Secrets

1. The real `.env` is only on the server, with `chmod 600` so only my user can read it. The repo has `deploy/production.env.example` with placeholders.
2. The server gets its own Postgres password (`openssl rand -hex 32`, 64 random hex characters) and its own `TOKEN_ENCRYPTION_KEY`, not the laptop's. Hex is used because characters like `@` or `/` would break `DATABASE_URL`.
3. If the encryption key is lost, the Google tokens and addresses in the database can't be read, and everyone signs in and enters their address again. So I keep a copy in a password manager.
4. `ADMIN_EMAIL` on the server is my own Google account, so only I can open `/stats`.

### 7. The server setup script

`deploy/server-setup.sh` runs once with `sudo`. Every step checks before it changes anything, so running it twice is safe.

1. **Docker** from Docker's own apt repo, which is newer than Ubuntu's. `!reset` needs Compose 2.24 or newer.
2. **Swap**: 1 GB of RAM isn't enough to build the website with Vite and run Postgres at the same time. A 2 GB swap file lets Linux move idle memory to disk instead of killing a process. It's in `/etc/fstab`, so it comes back after a reboot.
3. **Toronto time** for the server clock, so the cron times (3:30 am backup, 4:30 am reboot) are local. The app itself doesn't depend on it: it always uses each user's own time zone.
4. **ufw**: everything in is blocked except SSH (22), 80, and 443. Azure's network rules block everything else before it even reaches the VM, so this is a second layer. Note from section 5: Docker's published ports skip ufw, which is why only Caddy publishes any.
5. **SSH keys only**: a file in `/etc/ssh/sshd_config.d/` turns off passwords and root login. sshd keeps the first value it reads, and files load in name order, so the file is called `10-prayerfit.conf` to come before Azure's `50-cloudimg-settings.conf`. `sshd -t` checks the config before reloading, so a mistake can't lock me out. The Azure rule for port 22 also only allows my own IP.
6. **Automatic security updates**: `unattended-upgrades` installs security updates every day. If one needs a reboot (usually a new kernel), it reboots at 4:30 am. That's after the 3:00 am nightly job and the 3:30 am backup.
7. **The backup cron job** in `/etc/cron.d/prayerfit-backup`.
8. **The `dc` shortcut** for the long `docker compose -f ... -f ...` command.

There are no default passwords anywhere: SSH has no password, Postgres gets a random one, and Postgres isn't reachable from outside the server anyway.

### 8. Backups

1. `pg_dump` writes the whole database as SQL. It runs inside the `db` container (`docker compose exec -T db`), so it uses the container's own `POSTGRES_USER` and `POSTGRES_DB` and needs no password.
2. `--clean --if-exists` puts a `DROP TABLE IF EXISTS` before each table, so restoring over the live database replaces it instead of failing on tables that already exist.
3. It writes to `.part` first and renames at the end. With `set -o pipefail`, a failed dump stops the script, so a half-written file never looks like a good backup.
4. Files older than 14 days are deleted. The privacy page says the same.
5. I tested it on my machine: ran a backup, restored it into the running database, and the row counts matched.
6. The backups are on the same disk, so they protect against my mistakes, not against losing the VM. Copying one to my laptop now and then covers that.

### 9. Updating after a PR

`deploy/update.sh`:

1. `git pull --ff-only origin main`. `--ff-only` stops if the server's copy has its own changes, instead of making a surprise merge.
2. `up -d --build --remove-orphans` rebuilds the images and replaces only the containers that changed. The backend runs `alembic upgrade head` when it starts, so migrations happen by themselves.
3. `docker image prune -f` deletes the old images, which would otherwise fill the 64 GB disk over time.
4. It checks `APP_ORIGIN/api/health` through Caddy, the same way a visitor gets there, and tries for up to 2.5 minutes. It prints `{"status":"ok","database":"ok"}` or tells me to look at the logs.

### 10. Google sign-in on the server

1. The same OAuth client as my laptop gets a second redirect URI: `https://prayerfit.canadacentral.cloudapp.azure.com/auth/google/callback`. Google matches it exactly, including `https` and no trailing slash.
2. **Testing mode for now**: only test users (up to 100) can sign in, and their sign-in expires every 7 days. The app already handles that with "Sign in again".
3. **Why not publish now**: publishing needs a home page and privacy policy on a domain I own and have verified in Google Search Console. I can't verify `cloudapp.azure.com`, because Microsoft owns it. So publishing waits for prayerfit.me.
4. **The privacy page** (`/privacy`): Google asks for one, and it has to be public. It lists what's stored, the 2 calendar scopes and what each one can see, who else gets data (Google, Photon, OpenRouteService, Azure), how to delete everything, and my contact email. It includes the sentence about Google's "Limited Use" rules, which Google's reviewers look for. The landing page links to it in a small footer, since Google checks that the home page links to the privacy policy.

### 11. Switching to prayerfit.me

1. DNS: an A record sends prayerfit.me to the VM's static IP. That's why the IP is static: a dynamic one could change when the VM restarts.
2. `.env`: `SITE_ADDRESS` lists the new names and the old Azure address, and `APP_ORIGIN` and `GOOGLE_REDIRECT_URI` move to prayerfit.me. Caddy gets the new certificates and redirects the old address.
3. Google: add the new redirect URI first, then verify the domain, set the home page and privacy links, and publish.

### 12. Tests

1. `web/tests/privacy.spec.ts`: the page opens with no sign-in and never calls `/api/me`, it shows both scopes, the Limited Use link, and my email, the landing page's Privacy link opens it, and it's no wider than a phone screen.
2. `web/tests/sign-in.spec.ts`: the landing page's footer now has only the Privacy link, still no OpenStreetMap credit.
3. GitHub Actions has a new `deploy-files` job: `docker compose config` on the production files, and `bash -n` plus `shellcheck` on the 3 scripts.
4. Counts: `npx playwright test` in `web` gives `264 passed`.

### 13. How I checked it

1. On my machine, the whole production stack (with `SITE_ADDRESS=:80`, plain http) started: `/api/health` answered through Caddy, `/privacy` loaded, another host name got a 308 to `APP_ORIGIN`, `/auth/google/login` sent me to Google with the production redirect URI, a POST from another site still got 403, only Caddy had public ports, and the worker logged "Worker started".
2. Backup and restore worked as in section 8.
3. Not tested here: `server-setup.sh` on a real Azure VM, and the Let's Encrypt certificate, which needs the real address. The README's "Check it works" list covers those on the server.

### 14. The /stats page: a range dropdown and a line that goes down

1. **Where**: `backend/app/stats.py` (`record_sign_up`, `record_deletion`, `user_totals`), `backend/app/models.py` (`UserCountChange`), `backend/alembic/versions/0013_user_count_changes.py`, `GET /admin/stats/users` in `backend/app/routers/stats.py`, and `web/src/StatsPage.tsx`.
2. **The problem**: the graph used to add up `users.created_at`. "Delete my account" deletes the user's row, so they disappeared from the past too. The line could only go up, and a deleted user made every earlier day look smaller than it really was.
3. **The fix: anonymous counts per hour**. `user_count_changes` has 3 columns: `hour` (the start of the hour in UTC), `signed_up`, and `deleted`.
   a) A new user adds 1 to `signed_up` for this hour. Signing in again adds nothing.
   b) Deleting an account adds 1 to `deleted` and leaves the old `signed_up` alone. So the line goes up on the day they joined and down on the day they left.
   c) No user ID, no email, and no foreign key. Several people in the same hour share one row, so a row can't be matched to a person. A test checks the columns are exactly these 3.
   d) Both writes are in the same commit as the sign-in or the delete, so a failed sign-in or delete never counts.
   e) It's an "upsert" (`INSERT ... ON CONFLICT DO UPDATE`): if the hour's row is already there, the counts are added to it, even if 2 people sign up at the same moment.
   f) The hour comes from the database's clock (`now()`), the same clock as `users.created_at`.
4. **The migration** fills the table from today's users, grouped by the hour they signed up. People who deleted their account before it ran can't be counted, since their rows are already gone.
5. **Points**: each point is the total users at the end of that hour or day, or right now for the current one. It's every sign-up minus every deletion up to then.
   a) 1, 2, and 3 days: one point per hour, 24, 48, or 72 points. Hours are real hours counted in UTC, so the night the clocks fall back has two "1:00 AM" points (EDT, then EST). A test checks this.
   b) 5, 7, and 30 days: one point per Toronto calendar day, ending today. Days move by calendar date, never by adding 24 hours. A test checks the week of Nov 1.
   c) All time: one point per day from the first sign-up.
   d) Changes before the first point are already in its total, so the line starts at the right height.
6. **The page**:
   a) The "Total users" card is gone. The graph has the same number at its right end.
   b) The dropdown asks the backend for the new range (`?range=1d`). If an older answer arrives late, it's ignored, so it never replaces a newer choice.
   c) 72 points are too many to tab through or point at one by one. An invisible box over the plot finds the point closest to the mouse or the finger. The keyboard uses the arrow keys, Home, and End.
   d) Dots only show when they'd be at least 16px apart. On a phone, 1 day has no dots, just the line and the picked point.
   e) Times use `America/Toronto` whatever the computer's own time zone is. The hour text comes from `timeText` in `labels.ts`, the same as the rest of the site.
   f) The masjid card is called "Masajid" (the plural), and that's the only place the word shows. The names column has a hidden "Name" header for screen readers, and the right column just says "Users".
7. **Privacy page**: it now says the app counts sign-ups and deletions per hour, with nothing that leads back to a person.
8. **Tests**: `test_stats.py` (the counts, each range, daylight saving, the endpoints), `test_migrations.py` (the migration groups users by hour and adds no ID or email column), and `stats.spec.ts` and `privacy.spec.ts` for the page. Counts: `pytest` gives `857 passed`, and `npx playwright test` gives `276 passed`.

### 15. The highlight, short labels, one line per setting, and prayer notifications

1. **The highlight**: on Settings, "every 5 minutes" in "Updates and changes are reflected on your calendar every 5 minutes." is in a `<mark class="highlight">`. It uses `--gold-highlight`, the same token as "praying on time" on the landing page, so both always match, and it's bold like that phrase. It stays inline so it wraps like normal text (`box-decoration-break: clone` keeps the rounded ends on each line). An earlier version highlighted "Updates and changes" instead. The sentence's wording never changed.
2. **Short labels** (`LABELS` in `labels.ts`):
   a) Settings used to show each setup question as the label, like "How early do you want to arrive before iqamah (daily prayers)?". Now each row has the shortest label that's still clear:

| Before | After |
|---|---|
| What's your location? | Location |
| Which masjid do you usually go to? | Main masjid |
| Which prayers do you usually pray at the masjid? | Prayers at the masjid |
| Generally speaking, which Jumuah would you like to attend? | Preferred Jumuah |
| Short name | Short name |
| How early do you want to arrive before iqamah (daily prayers)? | Arrive before iqamah |
| How early do you want to arrive before Jumuah (Friday prayer)? | Arrive before Jumuah |
| Prayer colour | Prayer colour |
| Drive colour | Drive colour |
| How early do you want to be notified before leaving for the masjid? | Notify before leaving for the masjid |
| How early do you want to be notified before prayer at home? | Notify for home prayers |

   b) Setup keeps the full questions (`QUESTIONS`), since that's where people first answer them. The location, masjid, and weekly editors on Settings are setup's own steps, so they still show setup's questions while open.
   c) Each row's label is also its name for screen readers and its Edit button, like "Edit arrive before iqamah". Before, those used separate names like "How early for prayers", so a screen reader heard something different from what was on screen.
   d) While editing, the form's title said the same thing as the field's label, so the title is now only for screen readers (`visually-hidden`).
3. **One line per setting** (`styles.css`, `.row-text`):
   a) Each row is a wrapping flex line: the label, then the answer, then **Edit**.
   b) The label and the answer each take their own width. If they fit side by side, they share the line. If they don't, the answer wraps under the label. On desktop, every Optional row fits. On a phone, short pairs like "Arrive before iqamah" and "5 minutes" fit, and longer ones like "Notify for home prayers" wrap.
   c) Headings use `text-wrap: balance` everywhere else, but in these rows it split short labels onto 2 lines when there was room, so the rows turn it off.
   d) While editing, `.inline-field` puts the label and its box or dropdown on one line the same way. It only applies inside `.settings-page`, because setup uses the same `MinutesField` and stays stacked there.
   e) A Playwright test measures the boxes on both screens and checks which rows share a line.
4. **Prayer notifications**:
   a) 2 settings in `user_settings`, added by migration `0014`: `leave_reminder_minutes` and `home_reminder_minutes`. Empty means "No notification". Both start at 5 minutes. The migration adds them with `server_default='5'`, and Postgres fills every existing row with a new column's default, so existing users get 5 too. A migration test checks that.
   b) There was a 3rd setting, "before iqamah at the masjid". I removed it, so masjid prayer blocks (Jumuah too) never get a reminder. The drive block's reminder comes before them anyway. Migration `0014` wasn't on `main` yet, so I changed it instead of adding a migration that drops the column.
   c) A new user's settings row is built in Python before it's saved, and a column default only applies when the row is saved. So `_empty()` in `user_settings.py` sets the 2 defaults itself, or a brand new user's Settings page would show "No notification". The API's optional step uses the same defaults when a field is left out, so skipping setup's optional page gives them too.
   d) The API only takes the dropdown's choices: 5, 10, 15, 20, 30, or null. 7, 0, 60, and "5" get 422.
   e) `event_plan.py` puts each one on the right events: drive blocks use "before leaving", and every home prayer uses "for home prayers". A masjid prayer moved home because the user is busy is a home prayer. No drive time means no drive block, so "before leaving" adds nothing.
   f) They're Google Calendar popup reminders (`reminders.overrides`), so there's no web push and no new service.
   g) **"No notification" really means none.** Before, an event with no reminder left out the `reminders` field, so Google used the calendar's own default reminders. Now every event sends `{"useDefault": false, "overrides": []}` when there's no reminder. Masjid prayer blocks always send that.
   h) **Drive blocks changed.** They used to get a popup right when it was time to leave. Now they follow "before leaving", which starts at 5 minutes before.
   i) **Only changed events are sent.** The calendar update already compares a hash of what Google would get with what Google last got. A new reminder changes the hash, so only events whose reminder changed go back to Google. Past events are never touched. A test changes "for home prayers" at 3 pm and checks that only future home prayers were sent.
   j) Because of g) and h), the first update after this goes out sends every upcoming event once, since each one's `reminders` changed. After that, only real changes are sent.
   k) Every Settings editor sends both notification values with its own change. Otherwise saving a colour would turn the notifications off. A Playwright test checks that.
5. **Tests**: `test_reminders.py` (the defaults, "No notification" on both, each setting on its own events, no reminder on masjid prayers or Jumuah, a prayer moved home, no drive block, changing a setting, and the API), `test_migrations.py` (0014), and `settings.spec.ts` (every label, the highlight, the one-line layout, and both dropdowns saving and staying after a reload on desktop and phone). Counts: `pytest` gives `873 passed`, and `npx playwright test` gives `280 passed`.

### 16. The users graph, YouTube Studio style

1. **Where**: `Graph` and `UsersCard` in `web/src/StatsPage.tsx`, and the `.graph-box` styles in `styles.css`. The backend didn't change.
2. **The big sentence**: "PrayerFit has 41 users" sits above the graph. Every range ends now, so the last point of whatever range is picked is today's total. It uses `toLocaleString`, so 1234 shows as "1,234", and 1 says "user", not "users".
3. **The line**: one path of straight segments (`M` then `L`s), 1.75px wide. No curve smoothing: a curve between 40 and 41 can bend below 40, which would draw a dip that never happened. There's no dot on each point. The only dot is the one for the point being looked at.
4. **The value labels** (`valueTicks`):
   a) They're on the right, like YouTube Studio's.
   b) Each step is a whole number from 1, 2, 2.5, or 5, times 1, 10, 100, and so on. Only whole steps count, so 2.5 is only used as 25, 250, and up.
   c) The code tries the steps from smallest up and takes the first one that needs 4 spans or fewer to get above the highest total. Then it shows 4 or 5 labels from 0.
   d) The top label is always above the highest total, so the line never touches the top.
   e) Some results: 42 gives 0, 20, 40, 60. 3 gives 0, 1, 2, 3, 4. 0 or 1 gives 0, 1, 2, 3. 999 gives 0, 250, 500, 750, 1K. 1,148 gives 0, 500, 1K, 1.5K. Tests check each of these.
   f) From 1,000 on, labels say "1K", "1.5K", "1.25K" (`valueText`).
5. **The bottom labels** (`labelledPoints`):
   a) Labels are always the same number of points apart, so they're evenly spaced.
   b) Hours land on round clock hours, like every 4 hours: 12 AM, 4 AM, 8 AM. Midnight shows the date instead, so 2 or 3 days of hours still say which day is which.
   c) Days count back from today, so today always has a label.
   d) The code tries steps from smallest up (1, 2, 3, 4, 6, 8, 12, 24 hours, or 1, 2, 3, 5, 7, 10, 14... days). It takes the first one with at most 7 labels that are far enough apart not to touch. It works out how wide a label is from its length, at 6.2px a character for 11px text ("Oct 20" measured 36px). That gives 5 to 7 labels on every range, on desktop and on a phone.
   e) Each label is centred under its point. The plot has 22px on the left, enough for half a date, so the first label can be centred too. When the first label was lined up with the left edge instead, it moved right into the second one on a phone.
6. **Hover**: an invisible box over the plot finds the point closest to the pointer, left to right. It reaches the right edge, so pointing at the value labels picks the newest point. A dot appears there with a dashed line down to 0. The card sits in a band above the plot, centred over the dot, so it never covers the line. Near either edge it slides inward. The total is large and bold. Tapping, the arrow keys, Home, and End work as before.
7. **Phones**: the graph is drawn at its real width, so its text keeps its size. The title and the dropdown wrap onto 2 lines when they don't fit side by side.
8. **A flaky Settings test, fixed**: 2 Settings tests sometimes failed in a full run and passed on their own. Both opened "Prayers at the masjid" and clicked Save straight away. A Settings row eases its height for 220ms when it opens or closes, with its overflow hidden. Playwright's trace showed it clicked Save in that window, and the click landed on nothing. A person can't tap that fast, but a test can. The short labels changed the row heights on phones, which made it happen more often. Now every test opens a row with `openEditor` (`tests/mock-api.ts`), which waits for the page's animations to finish before and after clicking Edit. The one test that checks the row eases open still uses a plain click, since it has to see the animation running.
   a) A 2nd test was too strict. It named phone rows that only just fit side by side, like "Notify before leaving for the masjid" and "5 minutes". GitHub's computer renders fonts a pixel or 2 wider, so that row wrapped there. Now the test checks the rule on every row: it measures the label, the 16px gap, and the answer. If they clearly fit, they must share the line. If they clearly don't, the answer must wrap. A pair within 2px of fitting can go either way, so it isn't checked.
9. **Tests** (`stats.spec.ts`):
   a) The sentence: "user" for 1, and "1,234" style numbers.
   b) The line: straight segments only, at most 2px wide, and no dots until you point.
   c) The value labels: on the right, for 9 different highest totals.
   d) The bottom labels: 5 to 7, evenly spaced to within a pixel, and never touching, for every range on desktop and phone.
   e) Hover: the dot, the card above it, and the large bold total.
   f) Tapping, the keyboard, and the card staying inside the graph.

### 17. The notifications on setup's optional page

1. **Labels**: "Notify before leaving" became "Notify before leaving for the masjid", which says where you're leaving for. "Notify before home prayers" became "Notify for home prayers", which is shorter and still clear.
2. **One dropdown, 2 pages**: `web/src/ReminderField.tsx` is the label and the dropdown. Setup's optional page and the Settings editor both use it, so the labels, the 6 choices, and the 5-minute default (`DEFAULT_REMINDER` in `labels.ts`) can't drift apart.
3. **Setup saves them**: Finish sends both values in the same `PUT /settings/optional` as the other optional answers, before `POST /setup/finish` fills the calendar. So the very first calendar already has the reminders. Skip sends the defaults, 5 and 5.
4. **Look**: on Settings, the label and the dropdown share a line when they fit. On setup, they stack like every other question there. The dropdown's border and size come from `.reminder-select`, so it looks the same on both pages.
5. **Test** (`setup.spec.ts`): both dropdowns start at 5 minutes with the same 6 choices. The test changes them to 15 minutes and No notification, finishes setup, and checks that the save came before the first calendar update. Then it checks that Settings shows the same 2 values, and still shows them after a reload.
6. **Counts**: `pytest` gives `873 passed`, and `npx playwright test` gives `320 passed`.

### 18. Number boxes for every minutes setting

1. **What changed**: the 2 notifications were dropdowns (No notification, 5, 10, 15, 20, 30). Now all 4 minutes settings use the same number box: "Arrive before iqamah", "Arrive before Jumuah", "Notify before leaving for the masjid", and "Notify for home prayers". It's the same on setup's optional page and on Settings.
2. **The box** (`MinutesField.tsx`):
   a) It takes whole minutes from 0 to 60, with "minutes" after it.
   b) `inputMode="numeric"` opens the number keypad on a phone.
   c) It has a new optional `hint` line under the box. The 2 notify boxes use it for "0 = no notification". The box's `aria-describedby` points at the hint, so a screen reader reads it with the box.
   d) `ReminderField.tsx`, the dropdown, is gone.
3. **What 0 means**: for the 2 notify settings, 0 means no notification, and Settings shows "No notification". For the 2 arrive settings, 0 means arriving right at iqamah or Jumuah, and Settings shows "0 minutes".
4. **Checks on the website**: `wholeMinutes` in `labels.ts` already checked the arrive boxes. Now the notify boxes use it too. Anything else (61, -1, 2.5, empty) shows "Enter a whole number of minutes from 0 to 60." and saves nothing.
5. **Checks on the backend**:
   a) `OptionalRequest` takes the notify settings as `int` from 0 to 60 with `strict=True`, like the arrive settings. So 2.5, "5", and null are refused, not rounded or guessed.
   b) FastAPI's normal 422 answer is a list of technical errors, which the website could only show as "Check what you typed and try again." So `main.py` has a handler for bad minutes that answers `{"detail": {"message": "Enter a whole number of minutes from 0 to 60.", "field": ...}}`. The website shows that message under the box.
   c) Other bad answers, like a colour that doesn't exist, keep FastAPI's usual answer.
6. **Existing users keep their values**:
   a) The database didn't change. 5, 10, 15, 20, and 30 are all whole numbers from 0 to 60, so they stay as they are.
   b) Someone who picked "No notification" in the old dropdown has an empty value. The API reads that as 0, which means the same thing.
   c) On the backend, 0 and empty both mean no reminder (`or None` in `user_settings.py`). New and skipped setups still start at 5 for both.
7. **Tests**:
   a) `test_reminders.py` covers any whole number (7 and 60), 0 meaning no reminder on the events, an empty value reading as 0, and the clear message. The message test runs for each of the 4 fields with 61, -1, 2.5, "5", and null.
   b) `settings.spec.ts` and `setup.spec.ts` cover the boxes, the hint, the keypad, 0, bad numbers, and the server's message. Counts: `pytest` gives `890 passed`, and `npx playwright test` gives `324 passed`.
