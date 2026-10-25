// A pretend backend for website tests. It answers /api/* and /auth/logout
// the way the real one does, keeps the saved settings in memory, and
// records every request so tests can check what the website sent.

import type { Page, Route } from "@playwright/test";
import type { Masjid, MasjidSuggestion, Me, Settings, Step } from "../src/types";

export const KMA: Masjid = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Kanata Muslim Association",
  address: "351 Sandhill Rd",
  source: "openstreetmap",
  distance_km: 1.1,
  iqamah_status: "Iqamah times not added yet",
};
export const STITTSVILLE: Masjid = { ...KMA, id: "22222222-2222-2222-2222-222222222222", name: "Stittsville Masjid", address: "Stittsville Main Street, Ottawa", distance_km: 5.8 };
export const TORONTO: Masjid = { ...KMA, id: "33333333-3333-3333-3333-333333333333", name: "Kanata Masjid Toronto", address: "Toronto", distance_km: 352.1 };

// What the pretend Photon knows about masjids, as the backend would send them.
// The street address one is for a masjid that isn't on the map.
type PretendMasjid = { masjid: Masjid; kind: MasjidSuggestion["kind"] };
const ON_THE_MAP: PretendMasjid[] = [KMA, STITTSVILLE, TORONTO].map((masjid) => ({ masjid, kind: "masjid" }));
const BY_ADDRESS: PretendMasjid = {
  kind: "address",
  masjid: {
    id: "44444444-4444-4444-4444-444444444444", name: null, address: "3500 Fallowfield Road, Ottawa, Ontario, Canada",
    source: "user", distance_km: 7.2, iqamah_status: "Iqamah times not added yet",
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
    missing: ["address", "masjid", "weekly"],
    address: null,
    place_name: null,
    time_zone: null,
    method: "isna",
    asr_method: "standard",
    main_masjid_choice: null,
    main_masjid: null,
    main_masjid_short_name: null,
    weekly: [],
    jumuah_saved: false,
    jumuah_masjids: [],
  };
}

export function finishedSettings(): Settings {
  return {
    setup_complete: true,
    missing: [],
    address: HOME_PLACE,
    place_name: HOME_PLACE,
    time_zone: "America/Toronto",
    method: "isna",
    asr_method: "standard",
    main_masjid_choice: "masjid",
    main_masjid: KMA,
    main_masjid_short_name: "KMA",
    weekly: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({
      weekday, fajr: false, dhuhr: weekday < 5, asr: false, maghrib: false, isha: weekday < 5,
    })),
    jumuah_saved: true,
    jumuah_masjids: [KMA, STITTSVILLE],
  };
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

  signedIn(settings: Settings = emptySettings(), me: Partial<Me> = {}) {
    this.settings = settings;
    this.me = { email: "hakeem@example.com", google_sign_in_needed: false, calendar_access: true, setup_complete: settings.setup_complete, ...me };
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
    return missing;
  }

  private saved(calendar: unknown = null) {
    this.settings.missing = this.missing();
    return { settings: this.settings, calendar: this.me?.setup_complete ? calendar ?? updated(3) : null };
  }

  async install(page: Page) {
    await page.route("**/api/**", (route) => this.handle(route));
    await page.route("**/auth/logout", (route) => this.handle(route));
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
      case "PUT /api/settings/methods":
        Object.assign(s, { method: body.method, asr_method: body.asr_method });
        return json(200, this.saved());
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
        if (body.choice === "home") {
          Object.assign(s, { main_masjid_choice: "home", main_masjid: null, main_masjid_short_name: null });
        } else {
          const masjid = this.savedMasjids.get(body.masjid_id);
          if (!masjid) return json(404, { detail: { message: "Pick a masjid from the suggestions." } });
          Object.assign(s, { main_masjid_choice: "masjid", main_masjid: masjid, main_masjid_short_name: body.short_name ?? null });
        }
        return json(200, this.saved(updated(20)));
      }
      case "PUT /api/settings/weekly":
        s.weekly = body.days;
        return json(200, this.saved(updated(2)));
      case "PUT /api/settings/jumuah":
        s.jumuah_saved = true;
        s.jumuah_masjids = body.masjid_ids.map((id: string) => this.savedMasjids.get(id)!);
        return json(200, this.saved());
      case "POST /api/setup/finish":
        s.setup_complete = true;
        this.me.setup_complete = true;
        s.missing = this.missing();
        return json(200, { settings: s, calendar: updated(70) });
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

function updated(sent: number) {
  return { status: "updated", sent, waiting: 0, message: `Calendar updated. ${sent} events sent to Google.` };
}
