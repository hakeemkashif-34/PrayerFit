# Muslim Calendar

A website that keeps your prayer times up to date in your Google Calendar.

See [Muslim_Calendar_App.md](Muslim_Calendar_App.md) for the full product description and [LEARNING.md](LEARNING.md) for how each part works.

## Stack

1. Backend: Python and FastAPI
2. Database: Postgres, with SQLAlchemy and Alembic for migrations
3. Sign-in: Google, done on the server with PKCE
4. Runs with Docker Compose
5. Tests: pytest, run by GitHub Actions on every push and pull request

## Run it with Docker

```bash
cp .env.example .env        # then edit the values
docker compose up --build
```

Docker runs the database migrations (`alembic upgrade head`) before starting the server.

Open http://localhost:8000/health. You should see `{"status":"ok","database":"ok"}`.

To see the error case, stop the database with `docker compose stop db` and refresh. You should get a 503 error and `{"status":"error","database":"unreachable"}`. Start it again with `docker compose start db`.

## Prayer times

Open http://localhost:8000/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24 to get Ottawa's prayer times for that day.

| Parameter | Required | Default | Example |
|---|---|---|---|
| `latitude` | yes | | `45.4215` |
| `longitude` | yes | | `-75.6972` |
| `date` | no | today in that time zone | `2026-10-24` |
| `method` | no | `isna` | `isna`, `mwl`, `egyptian`, `karachi`, `umm_al_qura` |
| `asr_method` | no | `standard` | `standard`, `hanafi` |
| `timezone` | no | `DEFAULT_TIMEZONE` from `.env`, or `America/Toronto` | `America/Edmonton` |

Every time comes back with where it came from (`"source": "calculated"`, the method, and the Asr method). http://localhost:8000/docs lists every endpoint and lets you try them in the browser.

## Google Calendar

I sign in with Google and the app adds today's 5 prayers to a calendar called "Prayers" that it creates in my Google account. It only asks for `openid`, `email`, and `calendar.app.created`, which lets it manage calendars it made itself and nothing else. No Gmail, and it can't see my other calendars.

### 1. Set up Google Cloud (once)

1. Go to https://console.cloud.google.com and create a project, for example "Muslim Calendar".
2. In **APIs & Services > Library**, search for **Google Calendar API** and click **Enable**.
3. Open **Google Auth Platform** (or **APIs & Services > OAuth consent screen**) and click **Get started**.
   a) App name: Muslim Calendar. User support email: your email.
   b) Audience: **External**.
   c) Contact email: your email. Agree and create.
4. In **Audience**, leave the publishing status as **Testing**. Under **Test users**, add the Google account you'll sign in with.
5. In **Data Access**, click **Add or remove scopes** and add:
   a) `openid`
   b) `.../auth/userinfo.email`
   c) `https://www.googleapis.com/auth/calendar.app.created` (paste it under "Manually add scopes" if it's not in the list)
6. In **Clients**, click **Create client**.
   a) Application type: **Web application**.
   b) Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
   c) Click **Create** and copy the client ID and client secret. Google only shows the secret once, so save it (or download the JSON).

In Testing mode, Google expires refresh tokens after 7 days. When that happens the app answers 401 with `"Google sign-in expired. Sign in again."` and a link to sign in. That's expected, not a bug.

### 2. Fill in `.env`

```bash
GOOGLE_CLIENT_ID=<the client ID>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<the client secret>
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
TOKEN_ENCRYPTION_KEY=<generated, see below>
APP_ORIGIN=http://localhost:8000
COOKIE_SECURE=true
SESSION_DAYS=30
```

Make the encryption key with:

```bash
docker compose build backend
docker compose run --rm --no-deps backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Sign in and add today's prayers

1. `docker compose up --build`
2. In the browser, open http://localhost:8000/auth/google/login (type it in the address bar; the "Try it out" button in `/docs` can't follow a redirect to Google).
3. Pick your test account. Google warns that the app isn't verified. Click **Continue**. Leave the calendar box ticked and allow.
4. You land on http://localhost:8000/docs, signed in.
5. Open `GET /me` > **Try it out** > **Execute**. You should see your email and `"calendar_access": true`.
6. Open `POST /prayers/today` > **Try it out**. The example body is Ottawa. Change the latitude, longitude, and time zone if you want, then **Execute**.
7. Open Google Calendar. A new calendar called **Prayers** has today's Fajr, Dhuhr, Asr, Maghrib, and Isha, each 15 minutes long. Each description says where the time came from, like `Calculated (ISNA, standard Asr)`.
8. Run `POST /prayers/today` again. Still 5 events, not 10.

| Endpoint | What it does |
|---|---|
| `GET /auth/google/login` | Starts sign-in (open it in the browser) |
| `GET /auth/google/callback` | Google sends you back here |
| `POST /auth/logout` | Signs out |
| `GET /me` | Who's signed in, and whether Google needs a new sign-in |
| `POST /prayers/today` | Adds today's 5 prayers to the Prayers calendar. Safe to run again |
| `GET /prayers/today/events` | Your saved events for today |

POST requests need an `Origin` header matching `APP_ORIGIN`. Browsers send it on their own. With curl, add `-H "Origin: http://localhost:8000"`.

## Run the tests

The tests need a real Postgres. The easiest way is to start only the database from Docker Compose.

```bash
cp .env.example .env            # skip if you already have one
docker compose up -d db         # start Postgres in the background

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Inside Docker the database is called "db", but from your laptop it's "localhost".
export DATABASE_URL=postgresql://muslim_calendar:change-me@localhost:5432/muslim_calendar
pytest
```

Use the same user, password, and database name as in your `.env`. You should see `311 passed`.

The tests never call the real Google. They use a fake Google (`tests/fake_google.py`) and fake keys, so no Google settings are needed to run them.

To run only the tests that don't need the database: `pytest -m "not database"` (`249 passed, 62 deselected`).

When you're done, stop Postgres with `docker compose down`.
