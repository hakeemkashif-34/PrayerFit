# Muslim Calendar App: Project Context

## About me and the goal

1. I'm Hakeem Kashif, a second-year Computer Science student at Carleton University in the AI and Machine Learning stream.
2. I'm building this as a resume project for software engineering internships.
3. The goal is a working website with real users that also covers the skills my job postings keep asking for.

---

## Skills to cover, in priority order

These are the gaps from my job postings. When there's a choice between tools, pick the one that covers a gap below, as long as it makes sense for the app.

1. **Python backend:** FastAPI
2. **Cloud:** Azure, using student credit
3. **Database:** Postgres
4. **Docker:** the app and database run with Docker Compose
5. **Algorithms:** fitting prayers around commitments and picking the best Jumuah slot
6. **Testing:** pytest for the backend, Playwright for the website, and GitHub Actions to run tests on every push
7. **Linux:** the app runs on a Linux server in the cloud

C and C++ aren't covered. AI is a stretch goal, not part of the core app, so the basics stay free to run no matter how many people use it.

---

## Tech stack

1. **Backend:** Python and FastAPI
2. **Database:** Postgres, with SQLAlchemy and Alembic for migrations
3. **Website:** React and TypeScript
4. **Sign-in:** Google sign-in, with access to Google Calendar only, never Gmail
5. **Calendar:** prayers go into a separate "Prayers" calendar that the app owns, so it never touches the user's other events
6. **Prayer times:** calculated in code, with a choice of calculation method and Asr method (standard or Hanafi)
7. **Background jobs:** a nightly job that updates every user's prayers
8. **Hosting:** Azure on student credit

---

## How we work

1. Build in small pieces with small, clear commits.
2. Don't stop to explain or quiz me after each piece. I'll go through everything at the end until I understand every file.
3. To make that possible, add clear comments, and keep a short LEARNING.md that explains what each part does and why it was built that way, updated after each milestone.
4. Leave some bugs for me to find and fix, so I have my own stories for interviews.
5. Never commit secrets. Keys go in a .env file that's in .gitignore.
6. The app must cost $0 a month. Use free tiers only, and ask me before anything that costs money.

---

## Accuracy rules

1. A wrong prayer time means a missed prayer, so every prayer time calculation needs tests.
2. Show where each time came from.
3. Never apply a masjid time change unless it came from the masjid's own published source or a masjid admin confirmed it.

---

## Lessons from a similar app

A friend built a related personal calendar app and shared a design handoff. It uses a different stack (Cloudflare Workers, D1), so don't copy the stack. Keep the stack above, but follow these lessons:

1. **No AI.** The friend's app used a paid AI service. This app doesn't. Everything is calculated or read by regular, tested code, so it stays free to run for every user.
2. **Keep prayer time and iqamah separate.** The calculated prayer time and the masjid's iqamah are different things. Store where every time came from (calculated, published by the masjid, or estimated), show whether it's fresh or stale, and never invent a missing iqamah.
3. **Masjid data sources.** Check whether a masjid already publishes its times on MAWAQIT before building anything else. Each source gets its own small adapter, so one source breaking doesn't break the app.
4. **Time zones.** Use America/Toronto by default but keep it configurable. Use local dates for days and weeks, and time-zone-aware times for events. Never move to the next day by adding 24 hours. Test daylight saving weeks.
5. **Google sign-in.** Use my own Google Cloud project. Do the sign-in on the server with state checks and PKCE, encrypt Google tokens in the database, refresh them on the server, and use HttpOnly session cookies. Ask for the narrowest calendar access that lets the app manage its own "Prayers" calendar.
6. **Syncing with Google Calendar.** Queue changes before sending them to Google, use Google's change tracking to detect edits made in Google Calendar, and show conflicts instead of overwriting them.
7. **Only write the near future.** Keep about the next 1 to 2 weeks of prayers in Google Calendar, and roll forward each night.
8. **Background jobs.** Save each job before running it, and give it a stable ID so retries don't duplicate work.
9. **Notifications.** Use web push with the app's own keys. Recheck the event right before sending, so moved or deleted prayers don't trigger alerts.
10. **Built for many users from day one.** Every table and request is scoped to a user. The friend's app was single-user, and that was its biggest limitation.
11. **Test the hard cases.** Daylight saving weeks, masjid time changes, stale data, and Google errors with zero unintended calendar writes. Test against a separate test Google Calendar, never a real one.

---

## Milestones

1. **Setup:** repo, Docker Compose, a basic FastAPI app, Postgres, and GitHub Actions running tests
2. **Prayer times:** calculate times for any location, with tests
3. **Google Calendar:** sign in with Google, create the "Prayers" calendar, and add today's prayers
4. **Setup questions and nightly updates:** address, masjid, which prayers at the masjid, Jumuah masjids, and daylight saving time
5. **Masjid times and Jumuah:** enter KMA's times by hand first, then pick the Jumuah slot that fits
6. **Edit page:** change prayers on the website, and keep the website and Google Calendar in sync both ways
7. **Commitments and notifications:** move prayers around other commitments, and alert users when something changes
8. **Deploy:** run it on Azure

Stretch goals, only after the 8 milestones work:

1. **AI timetable reading:** an AI reads a masjid's timetable from a photo, poster, or website when it changes. It runs once per masjid, not per user, so a free AI tier should cover it. A masjid admin confirms every time it reads before anyone's calendar changes.
2. **University jama'ah hub:** from Muslim_Calendar_App.md.

---

## Full product description

See Muslim_Calendar_App.md for the problems, features, and stretch goals.
