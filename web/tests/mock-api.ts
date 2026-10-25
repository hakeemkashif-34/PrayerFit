// A pretend backend for website tests. It answers /api/* and /auth/logout
// the way the real one does, keeps the saved settings in memory, and
// records every request so tests can check what the website sent.

import type { Page, Route } from "@playwright/test";
import type { ChoicesRequest, CommuteTime, JumuahChoices, JumuahSlot, Masjid, MasjidSuggestion, Me, Settings, SlotKey, Step } from "../src/types";

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
    jumuah_saved: false,
    jumuah_masjids: [],
    arrive_early_minutes: 0,
    jumuah_arrive_early_minutes: 5,
    jumuah_pick: null,
    commute_times: [],
    prayer_color_id: null,
    drive_color_id: null,
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
    jumuah_saved: true,
    jumuah_masjids: [KMA, STITTSVILLE],
    arrive_early_minutes: 5,
    jumuah_arrive_early_minutes: 10,
    jumuah_pick: null,
    commute_times: [],
    prayer_color_id: "7",
    drive_color_id: null,
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
  // This Friday's Jumuah times by masjid ID, in slot order. A masjid that isn't here has none.
  jumuahTimes: Record<string, string[]> = { [KMA.id]: ["13:30", "14:30"], [STITTSVILLE.id]: ["13:15"] };
  // Busy times on the Friday, as ["13:00", "13:40"] clock pairs.
  busy: [string, string][] = [];
  // False is like a user without free/busy access: no busy times.
  busyChecked = true;
  // Jumuah length by masjid ID. Missing means 45 minutes, estimated.
  jumuahLength: Record<string, number> = {};
  // OpenRouteService's pretend driving estimates, in minutes. A masjid that isn't here has no estimate.
  orsMinutes: Record<string, number> = { [KMA.id]: 14, [STITTSVILLE.id]: 20 };
  // The user's own commute times, by masjid ID.
  commuteMinutes: Record<string, number> = {};

  signedIn(settings: Settings = emptySettings(), me: Partial<Me> = {}) {
    this.settings = settings;
    this.optionalSaved = !settings.missing.includes("optional");
    this.me = {
      email: "hakeem@example.com", google_sign_in_needed: false, calendar_access: true, busy_access: true,
      setup_complete: settings.setup_complete, ...me,
    };
    this.commuteMinutes = Object.fromEntries(
      settings.commute_times.filter((c) => c.minutes !== null).map((c) => [c.masjid_id, c.minutes!]),
    );
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

  // Like the backend: the main masjid, then the Jumuah masjids, each once.
  private commuteTimes(): CommuteTime[] {
    const s = this.settings;
    const masjids = [...(s.main_masjid_choice === "masjid" && s.main_masjid ? [s.main_masjid] : []), ...s.jumuah_masjids];
    const unique = masjids.filter((m, i) => masjids.findIndex((x) => x.id === m.id) === i);
    return unique.map((m) => ({ masjid_id: m.id, masjid_name: m.name ?? m.address ?? "Your masjid", minutes: this.commuteMinutes[m.id] ?? null }));
  }

  // Like POST /jumuah/choices: every slot's window, and which one is selected.
  choices(body: ChoicesRequest): JumuahChoices {
    const s = this.settings;
    const empty: JumuahChoices = { friday: null, time_zone: null, busy_checked: false, busy: [], slots: [], selected: null };
    if (s.jumuah_masjids.length === 0) return empty;
    const early = body.jumuah_arrive_early_minutes ?? s.jumuah_arrive_early_minutes;
    const busy = this.busyChecked ? this.busy.map(([start, end]) => [Date.parse(friday(start)), Date.parse(friday(end))]) : [];
    const slots: JumuahSlot[] = [];
    s.jumuah_masjids.forEach((masjid) => {
      (this.jumuahTimes[masjid.id] ?? []).forEach((clock, i) => {
        const override = body.commute_minutes && masjid.id in body.commute_minutes ? body.commute_minutes[masjid.id] : undefined;
        const own = override === undefined ? this.commuteMinutes[masjid.id] ?? null : override;
        const commute = own ?? this.orsMinutes[masjid.id] ?? null;
        const length = this.jumuahLength[masjid.id] ?? 45;
        const start = Date.parse(friday(clock));
        const arrive = start - early * MINUTE;
        const leave = commute === null ? null : arrive - commute * MINUTE;
        const end = start + length * MINUTE;
        const from = leave ?? arrive;
        slots.push({
          masjid_id: masjid.id, masjid_label: masjid.id === s.main_masjid?.id && s.main_masjid_short_name ? s.main_masjid_short_name : masjid.name ?? "Your masjid",
          order: i + 1, order_label: `${["1st", "2nd", "3rd"][i]} Jumuah`,
          starts_at: iso(start), leave_at: leave === null ? null : iso(leave), arrive_at: iso(arrive), ends_at: iso(end),
          commute_minutes: commute, commute_source: commute === null ? null : own === null ? "ors" : "user",
          jumuah_minutes: length, length_estimated: !(masjid.id in this.jumuahLength),
          fits: !busy.some(([b0, b1]) => from < b1 && b0 < end),
        });
      });
    });
    const listed = s.jumuah_masjids.map((m) => m.id);
    slots.sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at) || listed.indexOf(a.masjid_id) - listed.indexOf(b.masjid_id));
    const key = (slot: JumuahSlot): SlotKey => ({ masjid_id: slot.masjid_id, order: slot.order });
    const pick = s.jumuah_pick;
    const picked = pick && slots.find((x) => x.masjid_id === pick.masjid_id && x.order === pick.order);
    const fitting = slots.find((x) => x.fits);
    const selected = picked ? key(picked) : fitting ? key(fitting) : slots[0] ? key(slots[0]) : null;
    return {
      friday: FRIDAY, time_zone: "America/Toronto", busy_checked: this.busyChecked,
      busy: this.busyChecked ? this.busy.map(([start, end]) => ({ starts_at: friday(start), ends_at: friday(end) })) : [],
      slots, selected,
    };
  }

  private saved(calendar: unknown = null) {
    this.settings.missing = this.missing();
    this.settings.commute_times = this.commuteTimes();
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
      return json(401, { detail: { message: "Not signed in.", reason: "not_signed_in", login_url: "/auth/google/login" } });
    }

    const key = `${request.method()} ${path}`;
    const s = this.settings;
    switch (key) {
      case "GET /api/me":
        return json(200, this.me);
      case "GET /api/settings":
        s.missing = this.missing();
        s.commute_times = this.commuteTimes();
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
        // Like the backend's follow_main_masjid: the main masjid is the first
        // Jumuah masjid, unless the user changed the Jumuah list themselves.
        const oldMain = s.main_masjid_choice === "masjid" ? s.main_masjid?.id ?? null : null;
        const newMain = body.choice === "home" ? null : body.masjid_id;
        const jumuahIds = s.jumuah_masjids.map((m) => m.id);
        if (oldMain !== newMain && (jumuahIds.length === 0 || (jumuahIds.length === 1 && jumuahIds[0] === oldMain))) {
          const picked = newMain ? this.savedMasjids.get(newMain) : undefined;
          s.jumuah_masjids = picked ? [picked] : [];
          if (picked) s.jumuah_saved = true;
        }
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
      case "PUT /api/settings/jumuah":
        s.jumuah_saved = true;
        s.jumuah_masjids = body.masjid_ids.map((id: string) => this.savedMasjids.get(id)!);
        if (s.jumuah_pick && !body.masjid_ids.includes(s.jumuah_pick.masjid_id)) s.jumuah_pick = null;
        return json(200, this.saved());
      case "PUT /api/settings/commute-times":
        for (const time of body.times as { masjid_id: string; minutes: number | null }[]) {
          if (time.minutes === null) delete this.commuteMinutes[time.masjid_id];
          else this.commuteMinutes[time.masjid_id] = time.minutes;
        }
        return json(200, this.saved(updated(4)));
      case "PUT /api/settings/jumuah-pick":
        s.jumuah_pick = body.masjid_id ? { masjid_id: body.masjid_id, order: body.order } : null;
        return json(200, this.saved(updated(2)));
      case "POST /api/jumuah/choices":
        return json(200, this.choices(body));
      case "PUT /api/settings/optional":
        this.optionalSaved = true;
        Object.assign(s, {
          arrive_early_minutes: body.arrive_early_minutes ?? 0,
          jumuah_arrive_early_minutes: body.jumuah_arrive_early_minutes ?? 5,
          main_masjid_short_name: s.main_masjid_choice === "masjid" ? body.short_name?.trim() || null : null,
          prayer_color_id: body.prayer_color_id ?? null,
          drive_color_id: body.drive_color_id ?? null,
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

// Masjids on the map whose words start with what was typed, closest first.
// Text with a number in it, or no masjid match, also gets the address one.
function suggestMasjids(query: string): PretendMasjid[] {
  if (query.trim().length < 3) return [];
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (text: string) => {
    const parts = text.toLowerCase().replace(/,/g, " ").split(/\s+/);
    return words.every((w) => parts.some((p) => p.startsWith(w)));
  };
  const found = ON_THE_MAP.filter(({ masjid }) => matches(`${masjid.name} ${masjid.address}`));
  if ((found.length === 0 || /\d/.test(query)) && matches(BY_ADDRESS.masjid.address!)) found.push(BY_ADDRESS);
  return found.slice(0, 5);
}

// Where a finished setup sends hakeem@example.com.
export const GOOGLE_CALENDAR = "https://calendar.google.com/calendar/r?authuser=hakeem%40example.com";

export function updated(sent: number) {
  return { status: "updated", sent, waiting: 0, message: `Calendar updated. ${sent} events sent to Google.` };
}
