// A pretend backend for website tests. It answers /api/* and /auth/logout
// the way the real one does, keeps the saved settings in memory, and
// records every request so tests can check what the website sent.

import type { Page, Route } from "@playwright/test";
import type {
  JumuahChoices, JumuahSlot, Masjid, MasjidSuggestion, Me, Preview, PreviewEvent, Settings, SlotKey, Stats, Step, UsersGraph,
} from "../src/types";

export const KMA: Masjid = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Kanata Muslim Association",
  address: "351 Sandhill Rd",
  source: "openstreetmap",
  distance_km: 1.1,
  iqamah_status: "Times from MAWAQIT, updated Oct 25, 2026",
};
export const STITTSVILLE: Masjid = {
  ...KMA, id: "22222222-2222-2222-2222-222222222222", name: "Stittsville Masjid", address: "Stittsville Main Street, Ottawa",
  distance_km: 5.8, iqamah_status: "Not linked to MAWAQIT, so calculated times are used",
};
export const TORONTO: Masjid = { ...KMA, id: "33333333-3333-3333-3333-333333333333", name: "Kanata Masjid Toronto", address: "Toronto", distance_km: 352.1 };

// What the pretend Photon knows about masjids, as the backend would send them.
// The street address one is for a masjid that isn't on the map.
type PretendMasjid = { masjid: Masjid; kind: MasjidSuggestion["kind"] };
const ON_THE_MAP: PretendMasjid[] = [KMA, STITTSVILLE, TORONTO].map((masjid) => ({ masjid, kind: "masjid" }));
const BY_ADDRESS: PretendMasjid = {
  kind: "address",
  masjid: {
    id: "44444444-4444-4444-4444-444444444444", name: null, address: "3500 Fallowfield Road, Ottawa, Ontario, Canada",
    source: "user", distance_km: 7.2, iqamah_status: "Not linked to MAWAQIT, so calculated times are used",
  },
};

export const HOME_PLACE = "200 Kanata Avenue, Ottawa, Ontario, Canada";
// Every place the pretend Photon knows, Canada first like the backend sends them.
export const PLACES = [
  HOME_PLACE,
  "200 Kanata Avenue, Rochester, New York, United States",
  "Kanata Centrum, Ottawa, Ontario, Canada",
  "1 Robson Street, Vancouver, British Columbia, Canada",
];
const CREDIT = { credit: "© OpenStreetMap contributors", credit_url: "https://www.openstreetmap.org/copyright" };

export function emptySettings(): Settings {
  return {
    setup_complete: false,
    missing: ["address", "masjid", "weekly", "optional"],
    address: null,
    place_name: null,
    time_zone: null,
    main_masjid_choice: null,
    main_masjid: null,
    main_masjid_short_name: null,
    weekly: [],
    arrive_early_minutes: 0,
    jumuah_arrive_early_minutes: 5,
    jumuah_pick: null,
    prayer_color_id: null,
    drive_color_id: null,
    // The defaults: none before iqamah, 5 minutes before leaving and at home.
    masjid_reminder_minutes: null,
    leave_reminder_minutes: 5,
    home_reminder_minutes: 5,
    masjid_notices: [],
  };
}

export function finishedSettings(): Settings {
  return {
    setup_complete: true,
    missing: [],
    address: HOME_PLACE,
    place_name: HOME_PLACE,
    time_zone: "America/Toronto",
    main_masjid_choice: "masjid",
    main_masjid: KMA,
    main_masjid_short_name: "KMA",
    weekly: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({
      weekday, fajr: false, dhuhr: weekday < 5, asr: false, maghrib: false, isha: weekday < 5,
    })),
    arrive_early_minutes: 5,
    jumuah_arrive_early_minutes: 10,
    jumuah_pick: null,
    prayer_color_id: "7",
    drive_color_id: null,
    // The defaults: none before iqamah, 5 minutes before leaving and at home.
    masjid_reminder_minutes: null,
    leave_reminder_minutes: 5,
    home_reminder_minutes: 5,
    masjid_notices: [],
  };
}

// The coming Friday in the pretend backend. Toronto is 4 hours behind UTC that day.
export const FRIDAY = "2026-10-30";
const OFFSET = "-04:00";
const MINUTE = 60_000;

// "13:30" on the Friday -> its time as an ISO string with the offset.
export function friday(clock: string): string {
  return `${FRIDAY}T${clock}:00${OFFSET}`;
}

function iso(time: number): string {
  const local = new Date(time - 4 * 60 * MINUTE).toISOString().slice(11, 16);
  return friday(local);
}

export type Recorded = { method: string; path: string; body: unknown };

export class MockApi {
  me: Me | null = null; // null: not signed in
  settings: Settings = emptySettings();
  requests: Recorded[] = [];
  // Masjids saved through /masjids/from-suggestion, by ID.
  savedMasjids = new Map<string, Masjid>([KMA, STITTSVILLE].map((m) => [m.id, m]));
  // Make the next call to this path answer with this error.
  failNext: Record<string, { status: number; detail: unknown }> = {};
  // Like optional_saved on the backend. The website never sees it, only "optional" in missing.
  optionalSaved = false;
  // What POST /api/setup/finish says about the calendar, and how long it takes.
  finishCalendar: unknown = updated(70);
  finishDelayMs = 0;
  // Every Google Calendar URL the page went to. A fake page answers, so no test reaches Google.
  googleVisits: string[] = [];
  // This week's Jumuah times by masjid ID, in slot order. A masjid that isn't here has none.
  jumuahTimes: Record<string, string[]> = { [KMA.id]: ["13:30", "14:30"], [STITTSVILLE.id]: ["13:15"] };
  // Jumuah length by masjid ID. Missing means 45 minutes, estimated.
  jumuahLength: Record<string, number> = {};
  // Drive minutes by masjid ID, like OpenRouteService. Missing means unknown.
  driveMinutes: Record<string, number> = { [KMA.id]: 14, [STITTSVILLE.id]: 20 };
  // False: "Delete my account" couldn't reach Google to remove the Prayers calendar.
  googleReachable = true;
  // The one email that can open /stats, like ADMIN_EMAIL. null: nobody.
  adminEmail: string | null = null;
  stats: Stats = {
    masjids: [
      { name: "Kanata Muslim Association", users: 30, mawaqit_linked: true },
      { name: "Jamia Omar", users: 8, mawaqit_linked: false },
      { name: "(picked by address)", users: 1, mawaqit_linked: false },
    ],
  };
  // The graph for each dropdown choice. Set one to change what the page gets.
  usersGraphs: Record<string, UsersGraph> = {
    // 7 days, the default. Someone deleted their account on Oct 24, so the line dips.
    "7d": {
      step: "day",
      points: [
        ["2026-10-20", 30], ["2026-10-21", 33], ["2026-10-22", 35], ["2026-10-23", 38],
        ["2026-10-24", 37], ["2026-10-25", 40], ["2026-10-26", 42],
      ].map(([day, total]) => ({ start: `${day}T00:00:00-04:00`, total: total as number })),
    },
    // 1 day: 24 hours ending at noon on Oct 26, Toronto time (UTC-4).
    "1d": {
      step: "hour",
      points: Array.from({ length: 24 }, (_, i) => ({
        start: new Date(Date.UTC(2026, 9, 25, 17 + i)).toISOString().replace(".000Z", "Z"),
        total: 40 + Math.floor(i / 12),
      })),
    },
  };
  // Every range the page asked for, in order.
  rangesAsked: string[] = [];
  // How many times POST /api/calendar/preview answers 409 before it works, like setup still saving.
  previewNotReady = 0;

  signedIn(settings: Settings = emptySettings(), me: Partial<Me> = {}) {
    this.settings = settings;
    this.optionalSaved = !settings.missing.includes("optional");
    this.me = {
      email: "hakeem@example.com", google_sign_in_needed: false, calendar_access: true, busy_access: true,
      setup_complete: settings.setup_complete, ...me,
    };
    return this;
  }

  calls(method: string, path: string): Recorded[] {
    return this.requests.filter((r) => r.method === method && r.path === path);
  }

  // Waits until the page has sent at least `count` of these requests. A click
  // only starts a request, so checking straight after it can be too early.
  async sent(method: string, path: string, count = 1): Promise<Recorded[]> {
    const deadline = Date.now() + 5000;
    while (this.calls(method, path).length < count) {
      if (Date.now() > deadline) throw new Error(`The page didn't send ${count} × ${method} ${path}`);
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    return this.calls(method, path);
  }

  private missing(): Step[] {
    const s = this.settings;
    const missing: Step[] = [];
    if (!s.address) missing.push("address");
    if (!s.main_masjid_choice) missing.push("masjid");
    if (s.main_masjid_choice !== "home" && s.weekly.length !== 7) missing.push("weekly");
    if (!this.optionalSaved) missing.push("optional");
    return missing;
  }

  // Like POST /jumuah/slots: each slot at this masjid (or the saved main masjid), and which one is selected.
  // Jumuah is always at the main masjid.
  slots(masjidId?: string | null): JumuahChoices {
    const s = this.settings;
    const main = s.main_masjid_choice === "masjid" ? s.main_masjid : null;
    const one = masjidId ? this.savedMasjids.get(masjidId)! : main;
    const masjids = one ? [one] : [];
    const slots: JumuahSlot[] = [];
    masjids.forEach((masjid) => {
      (this.jumuahTimes[masjid.id] ?? []).forEach((clock, i) => {
        const length = this.jumuahLength[masjid.id] ?? 45;
        const start = Date.parse(friday(clock));
        // Like the backend: leave = start - "how early" - the drive. Without a drive time, the arrival.
        const leave = start - (s.jumuah_arrive_early_minutes + (this.driveMinutes[masjid.id] ?? 0)) * MINUTE;
        slots.push({
          masjid_id: masjid.id, masjid_label: this.label(masjid),
          order: i + 1, order_label: `${["1st", "2nd", "3rd"][i]} Jumuah`,
          starts_at: iso(start), ends_at: iso(start + length * MINUTE), leave_at: iso(leave),
          jumuah_minutes: length, length_estimated: !(masjid.id in this.jumuahLength),
        });
      });
    });
    const listed = masjids.map((m) => m.id);
    slots.sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at) || listed.indexOf(a.masjid_id) - listed.indexOf(b.masjid_id));
    const key = (slot: JumuahSlot): SlotKey => ({ masjid_id: slot.masjid_id, order: slot.order });
    const pick = s.jumuah_pick;
    const picked = pick && slots.find((x) => x.masjid_id === pick.masjid_id && x.order === pick.order);
    const firsts = [...slots].sort((a, b) => listed.indexOf(a.masjid_id) - listed.indexOf(b.masjid_id) || a.order - b.order);
    const noTimes = masjids.filter((m) => !(this.jumuahTimes[m.id] ?? []).length).map((m) => this.label(m));
    return {
      time_zone: "America/Toronto", slots, selected: picked ? key(picked) : firsts[0] ? key(firsts[0]) : null,
      no_times: noTimes,
    };
  }

  // The name the user sees: the short name for the main masjid.
  private label(masjid: Masjid): string {
    const s = this.settings;
    return masjid.id === s.main_masjid?.id && s.main_masjid_short_name ? s.main_masjid_short_name : masjid.name ?? "Your masjid";
  }

  // Like POST /calendar/preview: this week at round times, with a drive block before masjid prayers.
  // The drive ends right when the prayer starts, back to back, like the real ones.
  preview(): Preview {
    const s = this.settings;
    const times: [PreviewEvent["prayer"], string, number][] = [
      ["fajr", "Fajr", 6 * 60 + 10], ["dhuhr", "Dhuhr", 13 * 60], ["asr", "Asr", 15 * 60 + 30],
      ["maghrib", "Maghrib", 18 * 60], ["isha", "Isha", 19 * 60 + 30],
    ];
    const label = s.main_masjid ? this.label(s.main_masjid) : "";
    const events: PreviewEvent[] = [];
    for (let n = 0; n < 7; n++) {
      // Mon Oct 26 to Sun Nov 1, 2026.
      const date = new Date(Date.UTC(2026, 9, 26 + n)).toISOString().slice(0, 10);
      const weekday = n;
      // Toronto is back on standard time (-05:00) from Nov 1.
      const offset = date >= "2026-11-01" ? "-05:00" : OFFSET;
      const at = (minutes: number) =>
        `${date}T${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}:00${offset}`;
      for (const [prayer, title, start] of times) {
        const atMasjid = s.main_masjid_choice === "masjid" && s.weekly.find((d) => d.weekday === weekday)?.[prayer];
        if (atMasjid) {
          events.push({ local_date: date, prayer, kind: "drive", title: `Drive to ${label}`, starts_at: at(start - 14), ends_at: at(start) });
        }
        events.push({ local_date: date, prayer, kind: "prayer", title: atMasjid ? `${title} at ${label}` : title, starts_at: at(start), ends_at: at(start + 10) });
      }
    }
    return { time_zone: "America/Toronto", prayer_color_id: s.prayer_color_id, drive_color_id: s.drive_color_id, events };
  }

  private saved(calendar: unknown = null) {
    this.settings.missing = this.missing();
    return { settings: this.settings, calendar: this.me?.setup_complete ? calendar ?? updated(3) : null };
  }

  // On the whole browser context, so the tab that Finish opens is covered too.
  async install(page: Page) {
    const context = page.context();
    await context.route("**/api/**", (route) => this.handle(route));
    await context.route("**/auth/logout", (route) => this.handle(route));
    await context.route("https://calendar.google.com/**", (route) => {
      this.googleVisits.push(route.request().url());
      return route.fulfill({ contentType: "text/html", body: "<title>Fake Google Calendar</title><h1>Fake Google Calendar</h1>" });
    });
  }

  private async handle(route: Route) {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.postData() ? JSON.parse(request.postData()!) : undefined;
    this.requests.push({ method: request.method(), path, body });
    const json = (status: number, data: unknown) => route.fulfill({ status, json: data });

    const failure = this.failNext[path];
    if (failure) {
      delete this.failNext[path];
      return json(failure.status, { detail: failure.detail });
    }
    if (path === "/auth/logout") {
      this.me = null;
      return route.fulfill({ status: 204 });
    }
    if (!this.me) {
      if (path.startsWith("/api/admin/stats")) return json(404, { detail: "Not Found" });
      return json(401, { detail: { message: "Not signed in.", reason: "not_signed_in", login_url: "/auth/google/login" } });
    }

    const key = `${request.method()} ${path}`;
    const s = this.settings;
    switch (key) {
      case "GET /api/me":
        return json(200, this.me);
      case "DELETE /api/account":
        // Like the backend: everything is gone, and the session with it.
        this.me = null;
        return json(200, { google_cleaned: this.googleReachable });
      case "GET /api/settings":
        s.missing = this.missing();
        return json(200, s);
      case "POST /api/setup/location/suggest":
        return json(200, { suggestions: suggest(body.query).map((label, index) => ({ index, label })), ...CREDIT });
      case "PUT /api/settings/location": {
        // A real save takes a moment. Without this, tests could race ahead of the page.
        await new Promise((resolve) => setTimeout(resolve, 300));
        const label = suggest(body.query)[body.index];
        Object.assign(s, { address: label, place_name: label, time_zone: "America/Toronto" });
        return json(200, this.saved());
      }
      case "POST /api/setup/masjid/suggest":
        if (!s.address) return json(409, { detail: { message: "Save your location first." } });
        return json(200, {
          suggestions: suggestMasjids(body.query).map(({ masjid, kind }, index) => ({
            index, kind, label: kind === "masjid" ? masjid.name : masjid.address,
            detail: kind === "masjid" ? masjid.address : null, distance_km: masjid.distance_km,
          })),
        });
      case "POST /api/masjids/from-suggestion": {
        const picked = suggestMasjids(body.query)[body.index];
        if (!picked) return json(404, { detail: { message: "That masjid isn't in the list any more. Search again." } });
        this.savedMasjids.set(picked.masjid.id, picked.masjid);
        return json(200, picked.masjid);
      }
      case "PUT /api/settings/main-masjid": {
        // Like the backend: Jumuah is always at the main masjid. Home means no pick,
        // and a new main masjid starts at its 1st Jumuah.
        if (body.choice === "home") s.jumuah_pick = null;
        else if (s.jumuah_pick?.masjid_id !== body.masjid_id) s.jumuah_pick = { masjid_id: body.masjid_id, order: 1 };
        if (body.choice === "home") {
          Object.assign(s, { main_masjid_choice: "home", main_masjid: null, main_masjid_short_name: null });
        } else {
          const masjid = this.savedMasjids.get(body.masjid_id);
          if (!masjid) return json(404, { detail: { message: "Pick a masjid from the suggestions." } });
          // Like the backend: a short name belongs to one masjid.
          const shortName = s.main_masjid?.id === masjid.id ? s.main_masjid_short_name : null;
          Object.assign(s, { main_masjid_choice: "masjid", main_masjid: masjid, main_masjid_short_name: shortName });
        }
        return json(200, this.saved(updated(20)));
      }
      case "PUT /api/settings/weekly":
        s.weekly = body.days;
        return json(200, this.saved(updated(2)));
      case "PUT /api/settings/jumuah-pick":
        s.jumuah_pick = body.masjid_id ? { masjid_id: body.masjid_id, order: body.order } : null;
        return json(200, this.saved(updated(2)));
      case "POST /api/jumuah/slots":
        return json(200, this.slots(body?.masjid_id));
      case "POST /api/calendar/preview":
        if (this.previewNotReady > 0 || !s.address || !s.main_masjid_choice) {
          this.previewNotReady = Math.max(0, this.previewNotReady - 1);
          return json(409, { detail: { message: "Finish setup first." } });
        }
        return json(200, this.preview());
      case "GET /api/admin/stats":
        if (!this.adminEmail || this.me.email !== this.adminEmail) return json(404, { detail: "Not Found" });
        return json(200, this.stats);
      case "GET /api/admin/stats/users": {
        if (!this.adminEmail || this.me.email !== this.adminEmail) return json(404, { detail: "Not Found" });
        const range = new URL(request.url()).searchParams.get("range") ?? "7d";
        this.rangesAsked.push(range);
        // Ranges with no graph of their own get the 7-day one.
        return json(200, this.usersGraphs[range] ?? this.usersGraphs["7d"]);
      }
      case "PUT /api/settings/optional":
        this.optionalSaved = true;
        Object.assign(s, {
          arrive_early_minutes: body.arrive_early_minutes ?? 0,
          jumuah_arrive_early_minutes: body.jumuah_arrive_early_minutes ?? 5,
          main_masjid_short_name: s.main_masjid_choice === "masjid" ? body.short_name?.trim() || null : null,
          prayer_color_id: body.prayer_color_id ?? null,
          drive_color_id: body.drive_color_id ?? null,
          masjid_reminder_minutes: body.masjid_reminder_minutes ?? null,
          // Left out gets the default, like the backend. null is "No notification".
          leave_reminder_minutes: body.leave_reminder_minutes === undefined ? 5 : body.leave_reminder_minutes,
          home_reminder_minutes: body.home_reminder_minutes === undefined ? 5 : body.home_reminder_minutes,
        });
        return json(200, this.saved(updated(20)));
      case "POST /api/setup/finish":
        await new Promise((resolve) => setTimeout(resolve, this.finishDelayMs));
        s.setup_complete = true;
        this.me.setup_complete = true;
        s.missing = this.missing();
        return json(200, { settings: s, calendar: this.finishCalendar });
      case "POST /api/calendar/sync":
        return json(200, updated(0));
    }
    throw new Error(`The mock API doesn't know ${key}`);
  }
}

// Like Photon: every word typed has to start a word in the place. At most 5.
function suggest(query: string): string[] {
  if (query.trim().length < 3) return [];
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return PLACES.filter((place) => {
    const parts = place.toLowerCase().replace(/,/g, " ").split(/\s+/);
    return words.every((w) => parts.some((p) => p.startsWith(w)));
  }).slice(0, 5);
}

// Masjids on the map within 100 km whose words start with what was typed,
// closest first. Text with a number in it also gets the address one.
function suggestMasjids(query: string): PretendMasjid[] {
  if (query.trim().length < 3) return [];
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (text: string) => {
    const parts = text.toLowerCase().replace(/,/g, " ").split(/\s+/);
    return words.every((w) => parts.some((p) => p.startsWith(w)));
  };
  const found = ON_THE_MAP.filter(({ masjid }) => (masjid.distance_km ?? 0) <= 100 && matches(`${masjid.name} ${masjid.address}`));
  if (/\d/.test(query) && matches(BY_ADDRESS.masjid.address!)) found.push(BY_ADDRESS);
  return found.slice(0, 5);
}

// Where a finished setup sends hakeem@example.com.
export const GOOGLE_CALENDAR = "https://calendar.google.com/calendar/r?authuser=hakeem%40example.com";

export function updated(sent: number) {
  return { status: "updated", sent, waiting: 0, message: `Calendar updated. ${sent} events sent to Google.` };
}
