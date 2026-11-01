# PrayerFit: technical details

How each part of PrayerFit works and why it was built that way. To run it yourself, see [SETUP.md](SETUP.md). For a file by file walkthrough, see [LEARNING.md](../LEARNING.md). For the full product description, see [PrayerFit_App.md](../PrayerFit_App.md).

## Stack

1. Website: React and TypeScript, built with Vite, served by nginx
2. Backend: Python and FastAPI
3. Database: Postgres, with SQLAlchemy and Alembic for migrations
4. Nightly job: its own worker service, same code as the backend
5. Sign-in: Google, done on the server with PKCE
6. Addresses and masjids: the free Photon search, built on OpenStreetMap data
7. Masjid times: each masjid's public MAWAQIT page, with calculated times when it can't be read
8. Drive times: OpenRouteService's free plan (no live traffic)
9. Runs with Docker Compose, on an Azure VM in Canada with Caddy for HTTPS
10. Tests: pytest for the backend, Playwright for the website, both run by GitHub Actions on every push and pull request

## How it runs

Docker Compose starts 4 services:

| Service | What it does |
|---|---|
| `web` | nginx. Serves the website and passes `/api/...` and `/auth/...` to the backend. The only service the browser talks to. |
| `backend` | FastAPI. Runs the database migrations (`alembic upgrade head`) before it starts. |
| `worker` | Background jobs, checked every minute: the nightly job, reading MAWAQIT, the 5-minute busy check, and queued calendar updates. |
| `db` | Postgres. |

The website and the API share one address (`http://localhost:8000`), so the browser treats them as the same site. That's what lets the session cookie and the Origin check work.

On the server, Caddy sits in front of `web` for HTTPS (see [Hosting](#hosting)).

## Prayer times

I calculate prayer times in my own code (`backend/app/prayer_times/`), not with a library. The calendar always uses ISNA with standard Asr. There is no setting for the method.

`backend/tests/test_prayer_times_reference.py` compares my times with 2 well-known libraries, adhanpy and praytimes, every day of a year. Only the tests use them. The app never does. Daylight saving weeks and high latitudes have their own tests (`test_daylight_saving.py`, `test_high_latitude.py`).

The `/prayer-times` endpoint shows the raw calculation. Open http://localhost:8000/api/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24 to get Ottawa's prayer times for that day.

| Parameter | Required | Default | Example |
|---|---|---|---|
| `latitude` | yes | | `45.4215` |
| `longitude` | yes | | `-75.6972` |
| `date` | no | today in that time zone | `2026-10-24` |
| `method` | no | `isna` | `isna`, `mwl`, `egyptian`, `karachi`, `umm_al_qura` |
| `asr_method` | no | `standard` | `standard`, `hanafi` |
| `timezone` | no | `DEFAULT_TIMEZONE` from `.env`, or `America/Toronto` | `America/Edmonton` |

Every time comes back with where it came from (`"source": "calculated"`, the method, and the Asr method).

## Google sign-in and Google Calendar

I sign in with Google and the app keeps the next 14 days of prayers in a calendar called "Prayers" that it creates in my Google account. It only asks for `openid`, `email`, `calendar.app.created`, and `calendar.freebusy`. `calendar.app.created` lets it manage calendars it made itself and nothing else. `calendar.freebusy` lets it see when I'm busy, so my prayers can fit around my day, but never what my events are. No Gmail, and it can't read my other calendars.

The app only checks my primary calendar for busy times. Checking my other calendars would need one more scope (`calendar.calendarlist.readonly`, to find them), so it doesn't. Busy times are never saved. If Google doesn't answer, the calendar update carries on, and any prayer that was already moved stays where it is (see "Moving prayers around your calendar" below).

Sign-in is done on the server (`backend/app/auth/`):

1. `/auth/google/login` sends the browser to Google with a random state and a PKCE code challenge.
2. Google sends the browser back with a one-time code and the same state, and the server checks the state.
3. The server swaps the code for tokens, proving with the PKCE code verifier that it started the sign-in.
4. Google tokens are encrypted with Fernet before they're saved (`backend/app/auth/crypto.py`), and refreshed on the server.
5. The browser only gets an HttpOnly session cookie, so page scripts can't read it.

The key (`TOKEN_ENCRYPTION_KEY`) encrypts Google tokens and home addresses. If it's lost or changed, everyone has to sign in and enter their address again.

Every event the app makes is private, so people you share your calendar with only see "busy".

In Google Calendar, the **Prayers** calendar has today and the next 13 days, like `Fajr` and `Dhuhr at KMA`. Prayers at the masjid say where. Every other prayer is just its name. Events have no description, except a prayer that was moved or clashes with your calendar (see "Moving prayers around your calendar"). Where your times come from is on the Settings page instead. Until your masjid is linked to MAWAQIT (below), masjid prayers use the calculated time.

If you move to another time zone, the Prayers calendar's time zone changes too.

## Masjid times from MAWAQIT

Masjid times come from each masjid's public page on [MAWAQIT](https://mawaqit.net). Users never see or do any of the linking. Linking a masjid by hand is a command on the server, not a website button, so a user can't link the wrong page for everyone.

### How the list works

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

Masjids that aren't on MAWAQIT get calculated prayer start times only, with no iqamah, for now.

### What it changes in the calendar

1. **Masjid prayers** use the masjid's iqamah. Settings shows where it came from, like `Times from MAWAQIT, updated Oct 25, 2026`. A day with no iqamah uses the calculated start time. An iqamah is never made up. `+0` on a MAWAQIT page means the iqamah is at the adhan time: KMA uses it for Asr and Isha on days when its set time would come before the adhan. If a page sets `fajrFixationComparedToShuruq`, Fajr's iqamah isn't used and the worker logs it, since that setting's format isn't known.
2. **Home prayers** use the main masjid's adhan time.
3. **Jumuah**: Jumuah is always at your main masjid. On the coming Friday (today, if it's Friday), Dhuhr becomes `Jumuah at <masjid>`. This is where your busy times come in, not in the setup question. It uses your pick (its 1st, 2nd, or 3rd Jumuah) if that slot fits your calendar, with no description. If it clashes, or that slot isn't on this Friday, it uses the earliest Jumuah that fits, and the description says `Your pick (1st Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits.` (or `isn't on this Friday`). If every one clashes, it uses the 1st Jumuah, and the description says `Every Jumuah clashes with your calendar, so this is the 1st Jumuah.` If you pray at home, or your masjid has no Jumuah times, there's no Jumuah and Friday follows your weekly prayers.
4. **Only the coming Friday** uses MAWAQIT's Jumuah times, since a MAWAQIT page only shows this week's. Later Fridays follow your weekly grid for Dhuhr, and say `This Friday's Jumuah times aren't published yet, so this follows your weekly prayers.` They change to Jumuah once a later read covers that Friday.
5. **Jumuah length**: each masjid can have its own, set on the server ([SETUP.md](SETUP.md#linking-a-masjid-by-hand)). Without one, the block is 45 minutes. The other prayer blocks are Fajr 10 minutes, Dhuhr 15, Asr 10, Maghrib 10, and Isha 15.
6. **Freshness**: each read saves a full 30-day calendar from MAWAQIT, so if MAWAQIT can't be read, the last times read are kept for up to 7 days.
   a) Under 24 hours since the last good read: the times are used.
   b) 24 hours to 7 days: the times are still used, and Settings shows a notice at the top: `KMA's times couldn't be confirmed since Oct 24, 2026. Your calendar is still using the last times read from MAWAQIT, and switches to calculated times on Oct 31, 2026 if they still can't be read.`
   c) Over 7 days: your calendar uses calculated times until a read works again, and the notice says `Your calendar is using calculated times until they're back.` A calculated start is never later than the iqamah, so you're early, never late.

MAWAQIT can block this at any time. After a 403, a 429, or 3 failed reads in a row, the app waits 24 hours before trying that masjid again, and keeps the last good times in the meantime.

## Drive times

Each masjid prayer gets a **Drive to <masjid>** block before it, from when to leave until you arrive. It gets a popup 5 minutes before you leave, which you can change or turn off in "Notifications" ([SETUP.md](SETUP.md#5-notifications)). Drive times come from [OpenRouteService](https://openrouteservice.org), which has a free plan. They're typical drive times with no live traffic. The app calls `https://api.heigit.org/openrouteservice/v2/directions/driving-car`. HeiGIT shut off the old address, `api.openrouteservice.org`, on September 28, 2026.

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

## Nightly job

The `worker` service updates every user's calendar at 3:00 am in their own time zone. It adds the newest day, fixes any times that changed, and never touches past events. The only events it ever deletes are future drive blocks that aren't needed any more, like when a prayer moves home. Not 2:00 am, because 2:00 am doesn't exist on the spring daylight saving day.

Each job is saved with an ID like `nightly:<user id>:2026-10-24` before it runs, so a retry or a second worker can't run it twice. If the worker was off at 3:00 am, it catches up when it starts. If one user's Google sign-in expired, their job is marked `needs_sign_in` and everyone else still gets updated.

## Usage stats

Counts only. Never emails, names, addresses, or anything else about a user.

1. **Total users**: everyone who ever signed in.
2. **Masjids**: each masjid at least 1 user picked as their main masjid, most users first. A masjid picked by its address shows as "(picked by address)", never the address. "(no MAWAQIT times)" means it isn't linked, so it's one to add to the MAWAQIT list.

The private /stats page has 2 cards:

1. **Total users over time**, styled like YouTube Studio's views graph, in PrayerFit's own colours and font:
   a) A dropdown at the top right: 1 day, 2 days, 3 days, 5 days, 7 days (the default), 30 days, or All time.
   b) One big sentence with today's total, like "PrayerFit has 41 users".
   c) One thin line with straight segments between points, and no dot on each point. A smoothed curve could draw a dip that never happened.
   d) 1 to 3 days have one point per hour. 5 days and up have one point per day. Each point is the total users at the end of that hour or day, or right now for the current one.
   e) Light grid lines with labels on the right: 4 or 5 whole numbers from 0, up to a round number just above the highest total, like 0, 20, 40, 60. With few users it's 0, 1, 2, 3. From 1,000 on they say "1K", "1.5K".
   f) 5 to 7 evenly spaced labels along the bottom: round hours (like every 4 hours) for 1 to 3 days, with the date at midnight, and dates for longer ranges.
   g) Point at the graph (or tap it on a phone) and a dot appears on the line at the closest point, with a card above it: the date, the hour when it's hourly, and the total in large bold text. Moving off the graph or tapping elsewhere hides it. With the keyboard, tab to the graph and use the arrow keys, Home, and End.
   h) All times are Toronto time.
   e) The line goes down when someone deletes their account. It's built from `user_count_changes`: how many people signed up and how many deleted their account in each hour. That table has no user ID, no email, and nothing else that leads back to a person.
2. **Masajid**: each masjid and how many users picked it, with a small "No MAWAQIT times" tag on masjids that aren't linked.

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
| `DELETE /account` | Deletes the account: the Prayers calendar, the app's Google access, and everything stored. Answers `{"google_cleaned": false}` when Google couldn't be reached |
| `GET /me` | Who's signed in, whether Google needs a new sign-in, whether the app can see busy times, and whether setup is done |
| `GET /settings` | Your saved setup answers |
| `POST /setup/location/suggest` | Up to 5 address suggestions from Photon for what's typed so far. Saves nothing |
| `PUT /settings/location` | Saves the suggestion the user picked (encrypted) and its time zone |
| `POST /setup/masjid/suggest` | Up to 5 masjids from Photon for what's typed so far, closest to home first, with distances. Adds addresses near home when no masjid matches. Saves nothing |
| `POST /masjids/from-suggestion` | Saves the picked suggestion as a masjid, for the main masjid or Jumuah |
| `PUT /settings/main-masjid` | Saves the main masjid, or "home". Picking a different masjid clears its short name |
| `PUT /settings/weekly` | Saves the weekly grid (7 days) |
| `PUT /settings/optional` | Saves both "how early" times, the short name, the 2 colours, and the 2 notifications. Skip sends the defaults. Every minutes value must be a whole number from 0 to 60, or it answers 422 with "Enter a whole number of minutes from 0 to 60." |
| `PUT /settings/jumuah-pick` | Saves your Jumuah pick as your main masjid and a slot (1st, 2nd, or 3rd), or clears it |
| `POST /jumuah/slots` | Each Jumuah slot at your main masjid (or the `masjid_id` given, for setup), with this week's times as an example, its leave time, which one is picked, and the masjid's name if it has no Jumuah times yet. No busy times. A POST because it may ask OpenRouteService for a drive time |
| `POST /calendar/preview` | This week's prayers and drive blocks at their real times, for the "Adding your prayers" page. Nothing goes to Google |
| `GET /admin/stats` | Each masjid's users, with whether it has MAWAQIT times. 404 for everyone but `ADMIN_EMAIL` |
| `GET /admin/stats/users?range=7d` | Total users over time for the graph. `range` is `1d`, `2d`, `3d` (one point per hour), `5d`, `7d`, `30d`, or `all` (one point per day). 404 for everyone but `ADMIN_EMAIL` |
| `POST /setup/finish` | Finishes setup and fills the next 14 days. The website calls it after the last question |
| `POST /calendar/sync` | Sends anything still waiting. Safe to run again |
| `POST /prayers/today` | Updates today's prayers and drive blocks from your saved settings. Safe to run again |
| `GET /prayers/today/events` | Your saved events for today |

POST and PUT requests need an `Origin` header matching `APP_ORIGIN`. Browsers send it on their own. With curl, add `-H "Origin: http://localhost:8000"`.

## Hosting

PrayerFit runs on one small Linux VM on Azure, with the same Docker Compose setup as my laptop plus Caddy in front for HTTPS. It's at https://prayerfit.canadacentral.cloudapp.azure.com until I switch to prayerfit.me.

### Why a VM

I compared 3 ways to host it on my Azure for Students credit ($100 for 12 months, no credit card):

| | Linux VM + Docker Compose | Azure Container Apps | App Service |
|---|---|---|---|
| Cost | VM (B2pts v2, Arm64) and a 64 GB disk are in the free tier. Only the static public IP uses credit, about $3 to $4 a month | Free request grant, but the always-on worker uses vCPU time all day, and Postgres needs Azure Database for PostgreSQL (free for 12 months, then paid) | Free F1 has no always-on and no background worker. B1 is about $13 a month, which runs past $100 |
| Effort | Lowest. Same compose file as my laptop | New config for every service, plus a managed database | Same Postgres problem, and the worker needs a second app |
| Skills | Linux (SSH, firewall, cron, swap, updates) and Cloud (VM, network rules, public IP, DNS, budgets) | Cloud only | Cloud only |

The VM covers both skills from my job postings and costs about $45 of the $100 over 12 months.

### What runs on the server

| File | What it does |
|---|---|
| `docker-compose.prod.yml` | Added on top of `docker-compose.yml`. Adds Caddy, restarts every service after a crash or reboot, limits log size, and takes away the public ports of `db` and `web` |
| `deploy/Caddyfile` | Caddy gets a free Let's Encrypt certificate for `SITE_ADDRESS`, renews it, sends http to https, and moves any other name to `APP_ORIGIN` |
| `deploy/production.env.example` | The server's `.env`, with placeholders only. The real `.env` only ever lives on the server |
| `deploy/server-setup.sh` | Run once: Docker, a 2 GB swap file, Toronto time, the ufw firewall, SSH keys only, automatic security updates, and the daily backup |
| `deploy/backup.sh` | Saves the database to `~/prayerfit-backups/` every day at 3:30 am and keeps 14 days |
| `deploy/update.sh` | After I merge a PR: pulls `main`, rebuilds, restarts, and checks `/api/health` |

Only Caddy is reachable from the internet, on ports 80 and 443. Postgres has no public port.

The VM is Arm64, not x86 like my laptop. Every image in the compose files (Postgres, Python, Node, nginx, and Caddy) has an Arm64 version, and Docker picks it by itself, so nothing changes in the files. The one difference: `timezonefinder` has no ready-made Arm64 package, so on the server pip builds it from source. There's no C compiler in the `python:3.13-slim` image, so it uses its pure-Python version instead of its C part. It gives the same time zones, a little slower, and it's only used when someone saves an address.

## Testing

The tests never call the real Google, Photon, MAWAQIT, or OpenRouteService. They use fakes (`tests/fake_google.py`, `tests/fake_photon.py`, `tests/fake_mawaqit.py`, and `tests/fake_ors.py`) and fake keys, so no real settings are needed.

GitHub Actions runs both (`.github/workflows/tests.yml`) on every push and every pull request, with a throwaway Postgres for the backend tests. No real keys are used anywhere. To run them yourself, see [Run the tests](SETUP.md#run-the-tests).
