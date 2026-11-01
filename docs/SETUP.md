# PrayerFit: setup and operations

Everything needed to run PrayerFit on a laptop, link masjids, deploy it to Azure, and run the tests. How each part works is in [TECHNICAL.md](TECHNICAL.md).

## Run it with Docker

```bash
git clone https://github.com/hakeemkashif-34/prayerfit.git
cd prayerfit
cp .env.example .env        # then edit the values
docker compose up --build
```

Open http://localhost:8000. That's the website.

**If you ran it before the rename to PrayerFit**, the old database lived in a volume named after the old project. Docker Compose now calls the project `prayerfit`, so it starts with a fresh, empty database in `prayerfit_db-data`. Change these 3 lines in your `.env` (keep your own password):

```
POSTGRES_USER=prayerfit
POSTGRES_DB=prayerfit
DATABASE_URL=postgresql://prayerfit:<your password>@db:5432/prayerfit
```

Then remove the old containers and volume. `docker volume ls` shows its exact name, which comes from the folder you cloned into, like `muslim-calendar_db-data`:

```bash
docker compose -p muslim-calendar down
docker volume rm muslim-calendar_db-data
```

The 4 services are listed in [TECHNICAL.md](TECHNICAL.md#how-it-runs).

Open http://localhost:8000/api/health. You should see `{"status":"ok","database":"ok"}`.

To see the error case, stop the database with `docker compose stop db` and refresh. You should get a 503 error and `{"status":"error","database":"unreachable"}`. Start it again with `docker compose start db`.

http://localhost:8000/api/docs lists every endpoint and lets you try them in the browser.

## Google Calendar

What the app asks Google for, and why, is in [TECHNICAL.md](TECHNICAL.md#google-sign-in-and-google-calendar).

### 1. Set up Google Cloud (once)

1. Go to https://console.cloud.google.com and create a project, for example "PrayerFit".
2. In **APIs & Services > Library**, search for **Google Calendar API** and click **Enable**.
3. Open **Google Auth Platform** (or **APIs & Services > OAuth consent screen**) and click **Get started**.
   a) App name: PrayerFit. User support email: your email. (If your project already has an older app name, change it here, since it's what people see on Google's sign-in screen.)
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
6. **Optional** (page 2): a short name like `KMA`, how many minutes before iqamah and before Jumuah you want to arrive (whole numbers from 0 to 60, 5 by default), a colour for prayer blocks and for drive blocks (Basil by default), and the 2 notifications (5 minutes by default, see "Notifications" below). **Back** goes to page 1 without losing anything typed here. **Skip** (top right) saves the defaults.
7. Press **Finish** (or **Skip**). Nothing is written to Google Calendar before this. A new tab opens and fills the screen: "Adding your prayers to Google Calendar...", "This can take up to 1 minute.", and a week calendar with times down the side. Each day fills in from Fajr to Isha at your real prayer times, about one block a second, in your prayer colour. Drive blocks slide in just before masjid prayers in your drive colour, with a small gap between a drive and its prayer so they never look like they overlap, and a caption says what's being added, like "Adding Thursday's Asr". With motion turned off on your device, it's a spinner instead. Once the calendar is filled, it shows Google Calendar for the account you signed in with. The first tab goes to the Settings page. If the update fails, the new tab shows the error with a link back to Settings, and Settings shows it too, with **Try again**. If your browser blocks the new tab, Settings says so, and **Open Google Calendar** is right there.
8. Calculated times always use ISNA with standard Asr. Jumuah is always at your main masjid. Praying at home means no Jumuah.

### 4. Change a setting

Coming back to the website later opens the **Settings** page. It never sends you to Google Calendar on its own. Press **Open Google Calendar** to go there. Settings has 2 white cards, side by side on a computer and one above the other on a phone. **Required** has your location, main masjid, weekly prayers, and your Jumuah pick (the same calendar view as setup). **Optional** has the short name, both "how early" times, both colours, and the 2 notification settings. Each item has a short label with your answer beside it on the same line, like "Arrive before iqamah" and "5 minutes". Setup still asks the full questions, like "How early do you want to arrive before iqamah (daily prayers)?". On a phone, the answer moves under the label only when the two don't fit side by side. While editing, the label and its box or dropdown share a line the same way. At the top, Settings says "Updates and changes are reflected on your calendar every 5 minutes.", with "every 5 minutes" in bold, in the same soft yellow as "praying on time" on the landing page.

The labels: Location, Main masjid, Prayers at the masjid, Preferred Jumuah, Short name, Arrive before iqamah, Arrive before Jumuah, Prayer colour, Drive colour, Notify before leaving for the masjid, and Notify for home prayers. Press **Edit** next to any one of them, change it, and press **Save**. The message at the top says how many events were sent to Google. Only future events that changed are sent. Past events are never touched. For example, ticking Asr on Tuesdays sends 2 events (the 2 Tuesdays in the window), not 70.

### 5. Notifications

2 optional settings add Google Calendar popup reminders. Each is a number box for whole minutes from 0 to 60, with "minutes" after it and "0 = no notification" under it. On a phone it opens the number keypad. Both start at 5 minutes, including for people who signed up before these settings existed. They're on setup's optional page and on Settings, with the same labels, choices, and defaults. Setup saves them before the first calendar update, so the first calendar already has them.

1. **Notify before leaving for the masjid**: drive blocks. With no drive block (no drive time), nothing is added.
2. **Notify for home prayers**: every prayer that isn't at the masjid, including a masjid prayer moved home because you're busy.

Masjid prayer blocks, Jumuah too, never get a reminder. The drive block's reminder comes before them anyway.

0 means no reminder at all, and Settings shows it as "No notification". The app tells Google not to use the calendar's own default reminders either. Changing a setting only sends the future events whose reminder changed. Past events are never touched.

### 6. Delete my account

At the very bottom of Settings, **Delete my account** (outlined in red) asks first: "This deletes your PrayerFit account, your settings, and the Prayers calendar from your Google Calendar. This can't be undone." Cancel is focused, so a stray Enter does nothing. **Delete my account** then:

1. Deletes the app's "Prayers" calendar from your Google account, so every prayer event goes with it. Nothing else in your Google account is touched.
2. Takes back the app's access to your Google account.
3. Deletes everything stored about you: your account, sessions, Google tokens, settings, prayer events, jobs, drive times, and any masjid you typed in by its address.
4. Signs you out and shows the landing page with "Your account has been deleted."

If Google can't be reached (or your Google sign-in had expired), everything stored is still deleted, and the landing page says you can delete the "Prayers" calendar in Google Calendar yourself.

## Masjid times from MAWAQIT

How matching, freshness, and the fallback work is in [TECHNICAL.md](TECHNICAL.md#masjid-times-from-mawaqit).

### My list of MAWAQIT masjids

MAWAQIT's search needs a login and it has no sitemap, so the app can't find a masjid's page by itself. I keep my own list in `backend/app/data/mawaqit_masjids.csv`, one masjid per line:

```
name,mawaqit_link,latitude,longitude
Kanata Muslim Association,https://mawaqit.net/en/id/9793,45.356128,-75.9283718
Mosquee de Gatineau - CIO,https://mawaqit.net/en/cio-gatineau,45.4290189,-75.732133
```

It has 23 masjids around Ottawa. The link is either a share link (`https://mawaqit.net/en/id/9793`, from MAWAQIT's Share button) or a page link (`https://mawaqit.net/en/cio-gatineau`). The app saves `id/9793` or `cio-gatineau` and reads the times from that link. A share link answers with the masjid's page straight away.

The backend and the worker load the file every time they start. Loading it again never adds a copy. If I fix a name or a location in the file, the saved one changes too.

**To add a masjid to the list**, add a line to the CSV and deploy. Or add it straight away on the server, then add the same line to the CSV so it's kept:

```bash
docker compose exec backend python -m app.admin add-mawaqit https://mawaqit.net/en/id/9793 --name "Kanata Muslim Association" --lat 45.356128 --lon -75.9283718
```

It prints any users' masjids it linked.

**To check how well the list covers an area**, `scan-area` asks OpenStreetMap's free Overpass API for every masjid within 40 km of Ottawa (or `--lat`, `--lon`, `--km`), and prints each one as `linked`, `no match`, or `unclear`. It only reports. Nothing is saved.

```bash
docker compose exec backend python -m app.admin scan-area
```

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

## Drive times

1. Sign up at https://account.heigit.org/signup and copy your API key.
2. Put it in `.env` as `ORS_API_KEY=...` and restart: `docker compose up -d`.

With no key, there are no drive blocks, and everything else works as before. Only the rounded coordinates of your home and your masjids are sent (about 100 m), never an address. Each drive time is saved for 30 days, or until your address or masjids change.

## Moving prayers around your calendar

How it works is in [TECHNICAL.md](TECHNICAL.md#moving-prayers-around-your-calendar).

See the checks with:

```bash
docker compose exec db psql -U prayerfit -c "SELECT id, status, events_sent, error FROM busy_check_jobs ORDER BY block_start DESC LIMIT 10"
```

To try it with the test account:
1. Make sure the worker is running (`docker compose up -d`).
2. Add an event to the test account's main calendar that covers one of today's or tomorrow's prayers.
3. Within 5 minutes, that prayer moves in the Prayers calendar, with a description like `Moved because of an event in your calendar (42 minutes after Dhuhr's start time).`
4. Delete the event. Within 5 minutes, the prayer is back at its normal time.

## Nightly job

How it works is in [TECHNICAL.md](TECHNICAL.md#nightly-job).

To run it now, for testing:

```bash
docker compose exec worker python -m app.worker run-now --email you@gmail.com
```

It prints something like `nightly:...:2026-10-24: done, 0 events sent to Google`. Run it again and it says `Already ran today. Add --force to run it again.` With `--force` it runs again and sends 0 events when nothing changed. Leave out `--email` to run it for every user.

See the jobs with:

```bash
docker compose exec db psql -U prayerfit -c "SELECT id, status, attempts, events_sent FROM nightly_jobs ORDER BY created_at"
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

**The private page**: put your own Google email in `.env` as `ADMIN_EMAIL=you@gmail.com` and restart. Sign in, then open http://localhost:8000/stats. What the page shows is in [TECHNICAL.md](TECHNICAL.md#usage-stats).

## Deploy

PrayerFit runs on one small Linux VM on Azure, with the same Docker Compose setup as my laptop plus Caddy in front for HTTPS. It's at https://prayerfit.canadacentral.cloudapp.azure.com until I switch to prayerfit.me. Why I picked a VM, and what each deploy file does, is in [TECHNICAL.md](TECHNICAL.md#hosting).

### 1. Azure portal

1. **Budget first.** Search for **Cost Management**, open **Budgets**, and click **Add**. Scope: the Azure for Students subscription. Amount: $10 a month. Alert: 50% of actual cost, to my email. This is free and warns me early if something starts costing more than expected.
2. **Resource group.** Search for **Resource groups** and click **Create**. Name: `prayerfit`. Region: **Canada Central**. My Azure for Students subscription only allows 5 regions: `belgiumcentral`, `denmarkeast`, `canadacentral`, `germanywestcentral`, and `norwayeast`. Canada Central is the only one in Canada.
3. **The VM.** Search for **Free services**, find **Linux Virtual Machine**, and click **Create**, so the free sizes are offered. On the **Basics** tab:
   a) Resource group: `prayerfit`. Name: `prayerfit`. Region: **(Canada) Canada Central**.
   b) Availability options: **No infrastructure redundancy required**.
   c) Security type: **Standard**. B2pts v2 doesn't support **Trusted launch**, so the size can't be picked until this is Standard.
   d) Image: **Ubuntu Server 24.04 LTS - Arm64 Gen2**.
   e) Size: **Standard_B2pts_v2** (Arm64, 2 vCPUs, 1 GiB, free services eligible). In Canada Central, B2ats v2 and B1s both showed "NotAvailableForSubscription", so the Arm one is the free size left.
   f) Authentication type: **SSH public key**. Username: `azureuser`. Key: **Generate new key pair**, named `prayerfit-key`.
   g) Public inbound ports: **Allow selected ports**, and select **SSH (22)**, **HTTP (80)**, and **HTTPS (443)**.
4. **Disks** tab: OS disk type **Premium SSD**, size **64 GiB (P6)**, which is the free one. Check **Delete with VM**.
5. **Networking** tab: Public IP: **Create new** (the default name is `prayerfit-ip`), SKU **Standard**, assignment **Static**. Check **Delete public IP and NIC when VM is deleted**.
6. **Management** tab: Auto-shutdown **off**, since the worker has to run all night.
7. **Review + create**, then **Create**. Download the private key (`prayerfit-key.pem`) when asked. Azure only offers it once. Keep it out of the repo.
8. **The free address.** Open the VM, click the public IP, then **Configuration**. DNS name label: `prayerfit`. Save. The site's address is now `prayerfit.<region>.cloudapp.azure.com`, like `prayerfit.canadacentral.cloudapp.azure.com`.
9. **Lock down SSH.** Ports 22, 80, and 443 were opened when the VM was made, all from any address. In the VM, open **Networking** (or **Network settings**):
   a) Edit the SSH (22) rule: Source **My IP address**, so only my own internet connection can try to SSH in. If my IP changes (a new Wi-Fi network), update this rule.
   b) Leave the HTTP (80) and HTTPS (443) rules open to everyone. Caddy needs port 80 for the Let's Encrypt check.
   c) Optional: the HTTPS rule is TCP only. HTTP/3 uses UDP on 443, so for it, add a rule with destination port `443`, protocol **UDP**, action **Allow**. Without it, browsers just use HTTP/2.
10. **The next day:** open **Cost Management > Cost analysis** and check that only the public IP shows a cost.

### 2. The server

On my laptop, connect with the key:

```bash
chmod 600 ~/Downloads/prayerfit-key.pem
ssh -i ~/Downloads/prayerfit-key.pem azureuser@prayerfit.canadacentral.cloudapp.azure.com
```

On the server:

```bash
git clone https://github.com/hakeemkashif-34/prayerfit.git ~/prayerfit
cd ~/prayerfit
sudo deploy/server-setup.sh
exit                     # log out and back in, so docker works without sudo
```

If the repo is private, `git clone` asks for a login. Make a read-only key on the server instead: `ssh-keygen -t ed25519 -f ~/.ssh/github -N ""`, paste `~/.ssh/github.pub` into GitHub under the repo's **Settings > Deploy keys** (leave write access off), then clone with `GIT_SSH_COMMAND="ssh -i ~/.ssh/github" git clone git@github.com:hakeemkashif-34/prayerfit.git ~/prayerfit` and run `git config core.sshCommand "ssh -i ~/.ssh/github"` inside it.

SSH in again and fill in `.env`:

```bash
cd ~/prayerfit
cp deploy/production.env.example .env
chmod 600 .env
openssl rand -hex 32      # the Postgres password, used twice in .env
docker run --rm python:3.13-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
nano .env
```

In `.env`:
1. Paste the password into `POSTGRES_PASSWORD` and `DATABASE_URL`, and the key into `TOKEN_ENCRYPTION_KEY`. Save both somewhere safe, like a password manager, not the repo.
2. If the address isn't `prayerfit.canadacentral.cloudapp.azure.com`, change `SITE_ADDRESS`, `APP_ORIGIN`, and `GOOGLE_REDIRECT_URI` to match.
3. Copy `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `ORS_API_KEY` from my laptop's `.env`.
4. Put my real email in `OSM_CONTACT_EMAIL` and `ADMIN_EMAIL`. `ADMIN_EMAIL` must be the Google account I sign in with, so I can open `/stats`.

Then start it:

```bash
deploy/update.sh
```

The first build takes a few minutes. Caddy gets the certificate within a minute of starting, and the script ends by printing `{"status":"ok","database":"ok"}`.

### 3. Google Cloud Console

In the same project as my laptop:

1. **Clients**, then my web client:
   a) Authorized JavaScript origins: add `https://prayerfit.canadacentral.cloudapp.azure.com`.
   b) Authorized redirect URIs: add `https://prayerfit.canadacentral.cloudapp.azure.com/auth/google/callback`. Keep the localhost one for my laptop. Save. It can take a few minutes to work.
2. **Branding**:
   a) Application home page: `https://prayerfit.canadacentral.cloudapp.azure.com`
   b) Application privacy policy link: `https://prayerfit.canadacentral.cloudapp.azure.com/privacy`
   c) Authorized domains: add `cloudapp.azure.com` if Google accepts it. If it refuses, leave a), b), and c) empty until prayerfit.me. Testing mode doesn't need them.
3. **Audience**: leave the publishing status as **Testing**. Add each early user's Gmail under **Test users** (up to 100). Only test users can sign in, and their sign-in expires every 7 days, so they see **Sign in again** once a week. Publishing waits for prayerfit.me (below).

### 4. Check it works

1. Open https://prayerfit.canadacentral.cloudapp.azure.com. The browser shows a lock.
2. Sign in with my test account, finish setup, and check that the Prayers calendar fills in Google Calendar.
3. Open `/stats` with my account.
4. On the server:

```bash
cd ~/prayerfit
# dc is a shortcut from server-setup.sh for:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml
dc ps                          # 5 services, all "Up"
dc logs worker | head          # "Worker started. Checking for due jobs every 60 seconds."
sudo ufw status                # only 22, 80, 443
deploy/backup.sh               # a backup right now, in ~/prayerfit-backups/
```

From my laptop, `ssh -o PubkeyAuthentication=no azureuser@prayerfit.canadacentral.cloudapp.azure.com` should fail with `Permission denied (publickey)`.

### After merging a PR

```bash
ssh -i ~/Downloads/prayerfit-key.pem azureuser@prayerfit.canadacentral.cloudapp.azure.com
cd ~/prayerfit && deploy/update.sh
```

Migrations run by themselves when the backend starts. If I changed `.env`, run `deploy/update.sh` too, so the containers pick it up.

### Logs, backups, and restoring

```bash
dc logs -f --tail 100 backend      # or worker, caddy, web, db
ls -lh ~/prayerfit-backups/        # one file per day, 14 days kept
cat ~/prayerfit-backups.log        # what the 3:30 am backup printed
```

The backups sit on the same disk as the database, so they cover mistakes (a bad migration, a deleted table), not a lost VM. Now and then I copy the newest one to my laptop: `scp -i ~/Downloads/prayerfit-key.pem azureuser@prayerfit.canadacentral.cloudapp.azure.com:prayerfit-backups/prayerfit-YYYY-MM-DD.sql.gz .`

To restore one, stop the app so nothing writes during the restore, then load the file. Each backup drops and recreates every table first.

```bash
dc stop backend worker
gunzip -c ~/prayerfit-backups/prayerfit-YYYY-MM-DD.sql.gz | dc exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
dc start backend worker
```

### Switching to prayerfit.me

Once I have the domain from the GitHub Student Pack:

1. In the domain's DNS settings (Namecheap for .me): an **A record** for `@` pointing to the VM's static IP (shown on the VM's overview page), and a **CNAME record** for `www` pointing to `prayerfit.me.`. Wait until `nslookup prayerfit.me` shows the IP.
2. On the server, in `.env`:

```bash
SITE_ADDRESS=prayerfit.me, www.prayerfit.me, prayerfit.canadacentral.cloudapp.azure.com
APP_ORIGIN=https://prayerfit.me
GOOGLE_REDIRECT_URI=https://prayerfit.me/auth/google/callback
```

3. In Google Cloud Console, **before** restarting: add `https://prayerfit.me` to Authorized JavaScript origins and `https://prayerfit.me/auth/google/callback` to Authorized redirect URIs.
4. `deploy/update.sh`. Caddy gets certificates for the new names, and anyone using the old Azure address or `www` is sent to https://prayerfit.me. Everyone signs in once more, since cookies belong to one address.
5. In Google Cloud Console:
   a) **Branding**: home page `https://prayerfit.me`, privacy policy `https://prayerfit.me/privacy`, authorized domain `prayerfit.me`.
   b) Verify that I own prayerfit.me in [Google Search Console](https://search.google.com/search-console) with a DNS TXT record, using the same Google account as the Cloud project.
   c) **Audience**: click **Publish app**. If Google lists any of my scopes as sensitive, it asks for verification: a short video of the sign-in and how each scope is used, and the privacy page. Until it's approved, users see a "Google hasn't verified this app" warning and there's a 100-user cap. After publishing, sign-ins stop expiring every 7 days.
6. Update the addresses in this section and in `deploy/production.env.example`.

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
export DATABASE_URL=postgresql://prayerfit:change-me@localhost:5432/prayerfit
pytest
```

Use the same user, password, and database name as in your `.env`. You should see `890 passed`.

The tests never call the real Google, Photon, MAWAQIT, or OpenRouteService. They use fakes (`tests/fake_google.py`, `tests/fake_photon.py`, `tests/fake_mawaqit.py`, and `tests/fake_ors.py`) and fake keys, so no real settings are needed.

To run only the tests that don't need the database: `pytest -m "not database"` (`438 passed, 452 deselected`).

When you're done, stop Postgres with `docker compose down`.

### Website

```bash
cd web
npm ci
npx playwright install chromium   # once
npx playwright test
```

You should see `324 passed`: 162 tests, each on a desktop and a phone-sized screen. The tests mock the API, so the backend doesn't need to be running.
