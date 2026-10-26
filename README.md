# PrayerFit

PrayerFit puts your daily prayers and your masjid's times in your Google Calendar, planned around your day.

See [PrayerFit_App.md](PrayerFit_App.md) for the full product description and [LEARNING.md](LEARNING.md) for how each part works.

## Stack

1. Website: React and TypeScript, built with Vite, served by nginx
2. Backend: Python and FastAPI
3. Database: Postgres, with SQLAlchemy and Alembic for migrations
4. Nightly job: its own worker service, same code as the backend
5. Sign-in: Google, done on the server with PKCE
6. Addresses and masjids: the free Photon search, built on OpenStreetMap data
7. Masjid times: each masjid's public MAWAQIT page, with calculated times when it can't be read
8. Drive times: OpenRouteService's free plan (no live traffic)
9. Runs with Docker Compose
10. Tests: pytest for the backend, Playwright for the website, both run by GitHub Actions on every push and pull request

## Run it with Docker

```bash
cp .env.example .env        # then edit the values
docker compose up --build
```

Open http://localhost:8000. That's the website.

Docker Compose starts 4 services:

| Service | What it does |
|---|---|
| `web` | nginx. Serves the website and passes `/api/...` and `/auth/...` to the backend. The only service the browser talks to. |
| `backend` | FastAPI. Runs the database migrations (`alembic upgrade head`) before it starts. |
| `worker` | Background jobs, checked every minute: the nightly job, reading MAWAQIT, the 5-minute busy check, and queued calendar updates. |
| `db` | Postgres. |

The website and the API share one address (`http://localhost:8000`), so the browser treats them as the same site. That's what lets the session cookie and the Origin check work.

Open http://localhost:8000/api/health. You should see `{"status":"ok","database":"ok"}`.

To see the error case, stop the database with `docker compose stop db` and refresh. You should get a 503 error and `{"status":"error","database":"unreachable"}`. Start it again with `docker compose start db`.

http://localhost:8000/api/docs lists every endpoint and lets you try them in the browser.

## Prayer times

Open http://localhost:8000/api/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24 to get Ottawa's prayer times for that day.

| Parameter | Required | Default | Example |
|---|---|---|---|
| `latitude` | yes | | `45.4215` |
| `longitude` | yes | | `-75.6972` |
| `date` | no | today in that time zone | `2026-10-24` |
| `method` | no | `isna` | `isna`, `mwl`, `egyptian`, `karachi`, `umm_al_qura` |
| `asr_method` | no | `standard` | `standard`, `hanafi` |
| `timezone` | no | `DEFAULT_TIMEZONE` from `.env`, or `America/Toronto` | `America/Edmonton` |

Every time comes back with where it came from (`"source": "calculated"`, the method, and the Asr method).

## Google Calendar

I sign in with Google and the app keeps the next 14 days of prayers in a calendar called "Prayers" that it creates in my Google account. It only asks for `openid`, `email`, `calendar.app.created`, and `calendar.freebusy`. `calendar.app.created` lets it manage calendars it made itself and nothing else. `calendar.freebusy` lets it see when I'm busy, so my prayers can fit around my day, but never what my events are. No Gmail, and it can't read my other calendars.

The app only checks my primary calendar for busy times. Checking my other calendars would need one more scope (`calendar.calendarlist.readonly`, to find them), so it doesn't. Busy times are never saved. If Google doesn't answer, the calendar update carries on, and any prayer that was already moved stays where it is (see "Moving prayers around your calendar" below).

### 1. Set up Google Cloud (once)

1. Go to https://console.cloud.google.com and create a project, for example "PrayerFit".
2. In **APIs & Services > Library**, search for **Google Calendar API** and click **Enable**.
3. Open **Google Auth Platform** (or **APIs & Services > OAuth consent screen**) and click **Get started**.
   a) App name: PrayerFit. User support email: your email. (If you set this up as "Muslim Calendar" before, change the app name here, since it's what people see on Google's sign-in screen.)
   b) Audience: **External**.
   c) Contact email: your email. Agree and create.
4. In **Audience**, leave the publishing status as **Testing**. Under **Test users**, add the Google account you'll sign in with.
5. In **Data Access**, click **Add or remove scopes** and add:
   a) `openid`
   b) `.../auth/userinfo.email`
   c) `https://www.googleapis.com/auth/calendar.app.created` (paste it under "Manually add scopes" if it's not in the list)
   d) `https://www.googleapis.com/auth/calendar.freebusy` (same)

If your project was set up before milestone 5, go to **Google Auth Platform > Data Access** and add d). Then everyone who signed in before sees a **Sign in again** banner on Settings. Until they sign in again, their prayers don't move around their calendar.
6. In **Clients**, click **Create client**.
   a) Application type: **Web application**.
   b) Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
   c) Click **Create** and copy the client ID and client secret. Google only shows the secret once, so save it (or download the JSON).

The redirect URI is the same as in milestone 3. nginx passes `/auth/...` straight to the backend, so nothing in Google Cloud has to change.

In Testing mode, Google expires refresh tokens after 7 days. When that happens the website shows a **Sign in again** button instead of an error. That's expected, not a bug.

### 2. Fill in `.env`

```bash
GOOGLE_CLIENT_ID=<the client ID>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<the client secret>
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
TOKEN_ENCRYPTION_KEY=<generated, see below>
APP_ORIGIN=http://localhost:8000
COOKIE_SECURE=true
SESSION_DAYS=30
OSM_CONTACT_EMAIL=<your email>
```

`OSM_CONTACT_EMAIL` goes in the User-Agent of every request to Photon. It asks apps to give a way to contact the owner.

Make the encryption key with:

```bash
docker compose build backend
docker compose run --rm --no-deps backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The same key encrypts Google tokens and home addresses. If it's lost or changed, everyone has to sign in and enter their address again.

### 3. Go through setup

1. `docker compose up --build`
2. Open http://localhost:8000 and click **Sign in with Google**.
3. Pick your test account. Google warns that the app isn't verified. Click **Continue**. Leave the calendar box ticked and allow.
4. You land back on the website, on page 1 of 2. The 2 pages are listed on the left (on a phone, "Step 1 of 2" is at the top).
5. **Required** (page 1) has 4 questions on one page, all shown at once:
   a) **What's your location?** Start typing your address. Suggestions show up in a dropdown once you stop typing. Pick yours. It's saved right away, the box shows the address you picked (not what you typed), and the time zone comes from it. The list pushes the page down while it's open, so it never covers the next question. Postal codes aren't shown or saved, since OpenStreetMap's are often wrong in Canada.
   b) **Which masjid do you usually go to?** Start typing its name. Suggestions are masjids within 100 km of home, closest first, each with its distance. If nothing nearby matches, it says "No masjid found near you. Check the spelling, or type the masjid's address instead." Typing an address (with its number) finds a masjid that isn't on the map. Press **I pray at home** if you do: every prayer is at home and there's no weekly grid.
   c) **Which prayers do you usually pray at the masjid?** Tick them in the grid: prayers down the side, Monday to Sunday across the top. Anything left unticked is at home.
   d) **Generally speaking, which Jumuah would you like to attend?** It shows up as soon as you pick a masjid. It's a Friday in a day calendar, with times down the side from 11 AM to 4 PM. Each Jumuah slot (1st, 2nd, 3rd) at your masjid is a block covering just the Jumuah, from its start to its end (the masjid's Jumuah length, or 45 minutes when it isn't set), with "1st Jumuah" and a time like "1:30 to 2:15 PM". The blocks are in 1 column, one above the other, with a small gap between them. The rest of the day is greyed out. Click a block to pick it: it turns a light green with a small ✓ next to "1st Jumuah". The 1st Jumuah is picked for you. The times are this week's, only as an example: the pick is saved as "the 2nd Jumuah", not a clock time. It doesn't show your busy times. Jumuah is always at your main masjid. If it has no Jumuah times yet, it says "Jumuah times for <masjid> aren't available yet. We'll use the 1st Jumuah, and you can change it in Settings later." If you pray at home, there's no Jumuah, so there's no question.
   Press **Next** to save the masjid, the grid, and the Jumuah pick.
6. **Optional** (page 2): a short name like `KMA`, how many minutes before iqamah and before Jumuah you want to arrive (whole numbers from 0 to 60, 5 by default), and a colour for prayer blocks and for drive blocks (Basil by default). **Back** goes to page 1 without losing anything typed here. **Skip** (top right) saves the defaults.
7. Press **Finish** (or **Skip**). Nothing is written to Google Calendar before this. A new tab opens and fills the screen: "Adding your prayers to Google Calendar...", "This can take up to 1 minute.", and a week calendar with times down the side. Each day fills in from Fajr to Isha at your real prayer times, about one block a second, in your prayer colour. Drive blocks slide in just before masjid prayers in your drive colour, with a small gap between a drive and its prayer so they never look like they overlap, and a caption says what's being added, like "Adding Thursday's Asr". With motion turned off on your device, it's a spinner instead. Once the calendar is filled, it shows Google Calendar for the account you signed in with. The first tab goes to the Settings page. If the update fails, the new tab shows the error with a link back to Settings, and Settings shows it too, with **Try again**. If your browser blocks the new tab, Settings says so, and **Open Google Calendar** is right there.
8. Calculated times always use ISNA with standard Asr. Jumuah is always at your main masjid. Praying at home means no Jumuah.
9. Every event the app makes is private, so people you share your calendar with only see "busy".
10. In Google Calendar, the **Prayers** calendar has today and the next 13 days, like `Fajr` and `Dhuhr at KMA`. Prayers at the masjid say where. Every other prayer is just its name. Events have no description, except a prayer that was moved or clashes with your calendar (see "Moving prayers around your calendar"). Where your times come from is on the Settings page instead. Until your masjid is linked to MAWAQIT (below), masjid prayers use the calculated time.

### 4. Change a setting

Coming back to the website later opens the **Settings** page. It never sends you to Google Calendar on its own. Press **Open Google Calendar** to go there. Settings has 2 white cards, side by side on a computer and one above the other on a phone. **Required** has your location, main masjid, weekly prayers, and your Jumuah pick (the same calendar view as setup). **Optional** has the short name, both "how early" times, and both colours. Each item shows its setup question as the label and just your answer under it, like "How early do you want to arrive before iqamah (daily prayers)?" and "5 minutes". At the top, Settings says "Updates and changes are reflected on your calendar every 5 minutes." Press **Edit** next to any one of them, change it, and press **Save**. The message at the top says how many events were sent to Google. Only future events that changed are sent. Past events are never touched. For example, ticking Asr on Tuesdays sends 2 events (the 2 Tuesdays in the window), not 70.

If you move to another time zone, the Prayers calendar's time zone changes too.

## Masjid times from MAWAQIT

Masjid times come from each masjid's public page on [MAWAQIT](https://mawaqit.net). Users never see or do any of the linking. Linking a masjid by hand is a command on the server, not a website button, so a user can't link the wrong page for everyone.

### My list of MAWAQIT masjids

MAWAQIT's search needs a login and it has no sitemap, so the app can't find a masjid's page by itself. I keep my own list in `backend/app/data/mawaqit_masjids.csv`, one masjid per line:

```
name,mawaqit_link,latitude,longitude
Kanata Muslim Association,https://mawaqit.net/en/id/9793,45.356128,-75.9283718
Mosquee de Gatineau - CIO,https://mawaqit.net/en/cio-gatineau,45.4290189,-75.732133
```

It has 23 masjids around Ottawa. The link is either a share link (`https://mawaqit.net/en/id/9793`, from MAWAQIT's Share button) or a page link (`https://mawaqit.net/en/cio-gatineau`). The app saves `id/9793` or `cio-gatineau` and reads the times from that link. A share link answers with the masjid's page straight away.

The backend and the worker load the file every time they start. Loading it again never adds a copy. If I fix a name or a location in the file, the saved one changes too.

When a user picks a masjid in setup, the app matches it against the list straight away:

1. Within 100 m: a match, even if the names are different. Map names are often spelled differently, like "MAC QIC".
2. From 100 m to 200 m: a match only if the names closely match, ignoring words like masjid, mosque, association, centre, and Ottawa.
3. It links only if exactly 1 listed masjid matches. Otherwise it doesn't link, and the masjid shows on /stats with a "No MAWAQIT times" tag.

Then it reads the masjid's page right away, so the Jumuah question in setup already has the masjid's real Jumuah times. If MAWAQIT is down, picking the masjid still works, and calculated times are used until the worker reads it.

When the list changes, the masjids users already picked are matched again. An automatic link never replaces one I made with `link-mawaqit`, and a masjid I unlinked with `unlink-mawaqit` is never linked again automatically.

**To add a masjid to the list**, add a line to the CSV and deploy. Or add it straight away on the server, then add the same line to the CSV so it's kept:

```bash
docker compose exec backend python -m app.admin add-mawaqit https://mawaqit.net/en/id/9793 --name "Kanata Muslim Association" --lat 45.356128 --lon -75.9283718
```

It prints any users' masjids it linked.

**To check how well the list covers an area**, `scan-area` asks OpenStreetMap's free Overpass API for every masjid within 40 km of Ottawa (or `--lat`, `--lon`, `--km`), and prints each one as `linked`, `no match`, or `unclear`. It only reports. Nothing is saved.

```bash
docker compose exec backend python -m app.admin scan-area
```

Masjids that aren't on MAWAQIT get calculated prayer start times only, with no iqamah, for now.

### Linking a masjid by hand

1. Find the masjid's ID:

   ```bash
   docker compose exec backend python -m app.admin list-masjids
   ```

   Each line has the ID, the name, its MAWAQIT link (with "(automatic)" for one from the list, or "not linked"), and how many users picked it. A masjid only shows up once someone has picked it in setup. The /stats page (below) also lists every masjid users picked, most users first, with a "No MAWAQIT times" tag on the ones that aren't linked.

2. Link it to its MAWAQIT page:

   ```bash
   docker compose exec backend python -m app.admin link-mawaqit --masjid <masjid id> --url https://mawaqit.net/en/<masjid page>
   ```

   Only `https://mawaqit.net` links are accepted, and only the page name (or `id/<number>` for a share link) is saved. The widget link (`https://mawaqit.net/en/w/<masjid page>`) and share links (`https://mawaqit.net/en/id/9793`) work too. KMA's page is `https://mawaqit.net/en/kma-masjid-ottawa`. This replaces an automatic link.

3. The worker reads the page within a minute, then at most once every 6 hours. To read it now:

   ```bash
   docker compose exec backend python -m app.admin fetch-mawaqit --masjid <masjid id>
   ```

   Then `docker compose exec worker python -m app.worker run-now --force` to update calendars straight away.

4. To stop using a page: `python -m app.admin unlink-mawaqit --masjid <masjid id>`. Calendars go back to calculated times, and the masjid won't be linked automatically again. Linking it by hand undoes that.

5. To set how long a masjid's Jumuah is, from the khutbah to the end of the prayer (whole minutes from 15 to 90):

   ```bash
   docker compose exec backend python -m app.admin set-jumuah-length --masjid <masjid id> --minutes 40
   ```

   `list-masjids` shows each masjid's length, or "Jumuah length not set (45 min estimated)". Changing it updates the calendars of everyone who uses that masjid.

What it changes in the calendar:

1. **Masjid prayers** use the masjid's iqamah. Settings shows where it came from, like `Times from MAWAQIT, updated Oct 25, 2026`. A day with no iqamah uses the calculated start time. An iqamah is never made up. `+0` on a MAWAQIT page means the iqamah is at the adhan time: KMA uses it for Asr and Isha on days when its set time would come before the adhan. If a page sets `fajrFixationComparedToShuruq`, Fajr's iqamah isn't used and the worker logs it, since that setting's format isn't known.
2. **Home prayers** use the main masjid's adhan time.
3. **Jumuah**: Jumuah is always at your main masjid. On the coming Friday (today, if it's Friday), Dhuhr becomes `Jumuah at <masjid>`. This is where your busy times come in, not in the setup question. It uses your pick (its 1st, 2nd, or 3rd Jumuah) if that slot fits your calendar, with no description. If it clashes, or that slot isn't on this Friday, it uses the earliest Jumuah that fits, and the description says `Your pick (1st Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits.` (or `isn't on this Friday`). If every one clashes, it uses the 1st Jumuah, and the description says `Every Jumuah clashes with your calendar, so this is the 1st Jumuah.` If you pray at home, or your masjid has no Jumuah times, there's no Jumuah and Friday follows your weekly prayers.
4. **Only the coming Friday** uses MAWAQIT's Jumuah times, since a MAWAQIT page only shows this week's. Later Fridays follow your weekly grid for Dhuhr, and say `This Friday's Jumuah times aren't published yet, so this follows your weekly prayers.` They change to Jumuah once a later read covers that Friday.
5. **Jumuah length**: each masjid can have its own, set on the server (below). Without one, the block is 45 minutes. The other prayer blocks are Fajr 10 minutes, Dhuhr 15, Asr 10, Maghrib 10, and Isha 15.
6. **Freshness**: each read saves a full 30-day calendar from MAWAQIT, so if MAWAQIT can't be read, the last times read are kept for up to 7 days.
   a) Under 24 hours since the last good read: the times are used.
   b) 24 hours to 7 days: the times are still used, and Settings shows a notice at the top: `KMA's times couldn't be confirmed since Oct 24, 2026. Your calendar is still using the last times read from MAWAQIT, and switches to calculated times on Oct 31, 2026 if they still can't be read.`
   c) Over 7 days: your calendar uses calculated times until a read works again, and the notice says `Your calendar is using calculated times until they're back.` A calculated start is never later than the iqamah, so you're early, never late.

MAWAQIT can block this at any time. After a 403, a 429, or 3 failed reads in a row, the app waits 24 hours before trying that masjid again, and keeps the last good times in the meantime.

## Drive times

Each masjid prayer gets a **Drive to <masjid>** block before it, from when to leave until you arrive, with a popup reminder when it starts. Drive times come from [OpenRouteService](https://openrouteservice.org), which has a free plan. They're typical drive times with no live traffic. The app calls `https://api.heigit.org/openrouteservice/v2/directions/driving-car`. HeiGIT shut off the old address, `api.openrouteservice.org`, on September 28, 2026.

1. Sign up at https://account.heigit.org/signup and copy your API key.
2. Put it in `.env` as `ORS_API_KEY=...` and restart: `docker compose up -d`.

With no key, there are no drive blocks, and everything else works as before. Only the rounded coordinates of your home and your masjids are sent (about 100 m), never an address. Each drive time is saved for 30 days, or until your address or masjids change.

## Moving prayers around your calendar

Anything in my primary Google Calendar comes first, and each prayer works around it. The app only sees when I'm busy, never what the event is.

1. **At the masjid**: a masjid prayer stays at the masjid only if the drive, the "how early" minutes, and the prayer block are all free. Otherwise it's prayed at home that day, and its drive block is deleted.
2. **At the normal time** if that's free. The normal time is the iqamah for a masjid prayer that can't go to the masjid, and the adhan for every other prayer.
3. **Otherwise, the earliest free time** of at least 10 minutes, from the start of the prayer's time to its end. A gap shorter than the prayer's usual length shrinks it to fit, down to 10 minutes. For example, a 12-minute gap fits Isha as a 12-minute block. The description says how far after the prayer's start time (the adhan) it went, like `Moved because of an event in your calendar (42 minutes after Dhuhr's start time).` Over an hour it says `1 hour 12 minutes`, and right at the adhan it says `(at Dhuhr's start time)`.
4. **No free time at all**: it stays at the normal time, titled `Asr (clash)`, and the description says `Your event covers all of Asr's time today, so figure out a way to fit it in.`

Those are the only descriptions. The app only knows when I'm busy, never what my events are, so a description never names the event.

Each prayer's time ends at: Fajr, sunrise. Dhuhr, Asr. Asr, Maghrib. Maghrib, Isha. Isha, midnight, which is halfway between Maghrib and the next day's Fajr, so it never suggests 2 am.

Examples, with Isha at KMA (adhan 7:23 pm, iqamah 7:40 pm, a 10 minute drive):
1. A class until 7:35 pm: `Isha` at 7:40 pm, at home.
2. A class from 7:00 to 8:30 pm: `Isha` at 8:30 pm.
3. A meeting from 7:45 to 9:00 pm: `Isha` at 7:23 pm, before the meeting.

**Every 5 minutes**, the worker checks each user's busy times for today and tomorrow, and sends only the events that changed. So a new event moves the right prayer within 5 minutes, and deleting it puts the prayer back within 5 minutes. The nightly job still covers all 14 days. Each check is saved with an ID like `busy:<user id>:2026-10-26T19:45` before it runs, so it runs once per 5 minutes even with 2 workers.

It stays inside Google Calendar's free quota. Google doesn't charge under 1,000,000 requests a day per project, and allows 10,000 a minute per project and 600 a minute per user. For 1,000 users:
1. Busy checks: 288 a day each (every 5 minutes), so 288,000 a day. A quiet check is 1 free/busy call.
2. Everything else (the nightly job, moved prayers, settings changes): roughly 20,000 a day.
3. Total: about 310,000 a day, about 31% of the free 1,000,000.
4. Per minute: at most about 200 checks spread over each 5 minutes, well under 10,000. Each user makes about 1 call every 5 minutes, far under 600 a minute.
5. The free 1,000,000 would run out at around 3,200 users at this rate.

Things that never happen:
1. Events that already started are never moved. That includes a masjid prayer once its drive has started.
2. A moved prayer is never put in the past.
3. The Prayers calendar never counts as busy.
4. If free/busy doesn't answer, nothing that was moved is put back. The 5-minute check changes nothing at all and tries again next time.
5. Users who didn't allow free/busy get no moving. Everything works as before for them.

See the checks with:

```bash
docker compose exec db psql -U muslim_calendar -c "SELECT id, status, events_sent, error FROM busy_check_jobs ORDER BY block_start DESC LIMIT 10"
```

To try it with the test account:
1. Make sure the worker is running (`docker compose up -d`).
2. Add an event to the test account's main calendar that covers one of today's or tomorrow's prayers.
3. Within 5 minutes, that prayer moves in the Prayers calendar, with a description like `Moved because of an event in your calendar (42 minutes after Dhuhr's start time).`
4. Delete the event. Within 5 minutes, the prayer is back at its normal time.

## Nightly job

The `worker` service updates every user's calendar at 3:00 am in their own time zone. It adds the newest day, fixes any times that changed, and never touches past events. The only events it ever deletes are future drive blocks that aren't needed any more, like when a prayer moves home. Not 2:00 am, because 2:00 am doesn't exist on the spring daylight saving day.

Each job is saved with an ID like `nightly:<user id>:2026-10-24` before it runs, so a retry or a second worker can't run it twice. If the worker was off at 3:00 am, it catches up when it starts. If one user's Google sign-in expired, their job is marked `needs_sign_in` and everyone else still gets updated.

To run it now, for testing:

```bash
docker compose exec worker python -m app.worker run-now --email you@gmail.com
```

It prints something like `nightly:...:2026-10-24: done, 0 events sent to Google`. Run it again and it says `Already ran today. Add --force to run it again.` With `--force` it runs again and sends 0 events when nothing changed. Leave out `--email` to run it for every user.

See the jobs with:

```bash
docker compose exec db psql -U muslim_calendar -c "SELECT id, status, attempts, events_sent FROM nightly_jobs ORDER BY created_at"
```

## Usage stats

Counts only. Never emails, names, addresses, or anything else about a user.

```bash
docker compose exec backend python -m app.admin stats
```

It prints the same as the /stats page:

```
Total users: 42

Masjids:
  Kanata Muslim Association: 30
  Jamia Omar: 8  (no MAWAQIT times)
  (picked by address): 1  (no MAWAQIT times)
```

1. **Total users**: everyone who ever signed in.
2. **Masjids**: each masjid at least 1 user picked as their main masjid, most users first. A masjid picked by its address shows as "(picked by address)", never the address. "(no MAWAQIT times)" means it isn't linked, so it's one to add to the MAWAQIT list.

**The private page**: put your own Google email in `.env` as `ADMIN_EMAIL=you@gmail.com` and restart. Sign in, then open http://localhost:8000/stats. It has 3 parts:

1. "Total users: 42" at the top.
2. A graph of total users over time, one dot per day, from the first sign-up to today. Hover over a dot (or tap it on a phone, or tab to it) to see that day's date, how many signed up that day, and the total so far. It's worked out from each user's sign-up date, so nothing is saved each day.
3. A table of each masjid and how many users picked it, with a small "No MAWAQIT times" tag on masjids that aren't linked.

Anyone else, signed in or not, gets "Page not found". Nothing links to it. With `ADMIN_EMAIL` empty, nobody can open it.

## Look

Light only: white, black, and green, on a light green page. It looks the same whatever your device's dark mode setting is. The grey-green text for labels and hints is at least 5.6:1 against the light green, so it's easy to read.

## Endpoints

Through nginx, every endpoint below is under `/api` (like `/api/me`), except the `/auth/...` ones.

| Endpoint | What it does |
|---|---|
| `GET /auth/google/login` | Starts sign-in (open it in the browser) |
| `GET /auth/google/callback` | Google sends you back here, then to the website |
| `POST /auth/logout` | Signs out |
| `GET /me` | Who's signed in, whether Google needs a new sign-in, whether the app can see busy times, and whether setup is done |
| `GET /settings` | Your saved setup answers |
| `POST /setup/location/suggest` | Up to 5 address suggestions from Photon for what's typed so far. Saves nothing |
| `PUT /settings/location` | Saves the suggestion the user picked (encrypted) and its time zone |
| `POST /setup/masjid/suggest` | Up to 5 masjids from Photon for what's typed so far, closest to home first, with distances. Adds addresses near home when no masjid matches. Saves nothing |
| `POST /masjids/from-suggestion` | Saves the picked suggestion as a masjid, for the main masjid or Jumuah |
| `PUT /settings/main-masjid` | Saves the main masjid, or "home". Picking a different masjid clears its short name |
| `PUT /settings/weekly` | Saves the weekly grid (7 days) |
| `PUT /settings/optional` | Saves both "how early" times, the short name, and the 2 colours. Skip sends the defaults |
| `PUT /settings/jumuah-pick` | Saves your Jumuah pick as your main masjid and a slot (1st, 2nd, or 3rd), or clears it |
| `POST /jumuah/slots` | Each Jumuah slot at your main masjid (or the `masjid_id` given, for setup), with this week's times as an example, its leave time, which one is picked, and the masjid's name if it has no Jumuah times yet. No busy times. A POST because it may ask OpenRouteService for a drive time |
| `POST /calendar/preview` | This week's prayers and drive blocks at their real times, for the "Adding your prayers" page. Nothing goes to Google |
| `GET /admin/stats` | Total users, total users per day for the graph, and each masjid's users with whether it has MAWAQIT times. 404 for everyone but `ADMIN_EMAIL` |
| `POST /setup/finish` | Finishes setup and fills the next 14 days. The website calls it after the last question |
| `POST /calendar/sync` | Sends anything still waiting. Safe to run again |
| `POST /prayers/today` | Updates today's prayers and drive blocks from your saved settings. Safe to run again |
| `GET /prayers/today/events` | Your saved events for today |

POST and PUT requests need an `Origin` header matching `APP_ORIGIN`. Browsers send it on their own. With curl, add `-H "Origin: http://localhost:8000"`.

## Run the tests

### Backend

The backend tests need a real Postgres. The easiest way is to start only the database from Docker Compose.

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

Use the same user, password, and database name as in your `.env`. You should see `831 passed`.

The tests never call the real Google, Photon, MAWAQIT, or OpenRouteService. They use fakes (`tests/fake_google.py`, `tests/fake_photon.py`, `tests/fake_mawaqit.py`, and `tests/fake_ors.py`) and fake keys, so no real settings are needed.

To run only the tests that don't need the database: `pytest -m "not database"` (`437 passed, 394 deselected`).

When you're done, stop Postgres with `docker compose down`.

### Website

```bash
cd web
npm ci
npx playwright install chromium   # once
npx playwright test
```

You should see `246 passed`: 123 tests, each on a desktop and a phone-sized screen. The tests mock the API, so the backend doesn't need to be running.
