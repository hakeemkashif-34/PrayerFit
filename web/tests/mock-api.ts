// A pretend backend for website tests. It answers /api/* and /auth/logout
// the way the real one does, keeps the saved settings in memory, and
// records every request so tests can check what the website sent.

import type { Page, Route } from "@playwright/test";
import type { Masjid, Me, Nearby, Settings, Step } from "../src/types";

export const KMA: Masjid = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Kanata Muslim Association",
  address: "351 Sandhill Rd",
  source: "openstreetmap",
  distance_km: 1.1,
  iqamah_status: "Iqamah times not added yet",
};
export const STITTSVILLE: Masjid = { ...KMA, id: "22222222-2222-2222-2222-222222222222", name: "Stittsville Masjid", address: null, distance_km: 5.6 };
export const UNNAMED: Masjid = { ...KMA, id: "33333333-3333-3333-3333-333333333333", name: null, address: null, distance_km: 12.4 };

export const HOME_PLACE = "200 Kanata Avenue, Ottawa, Ontario, K2T 1K8, Canada";
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
  nearby: Nearby = { radius_km: 15, masjids: [KMA, STITTSVILLE, UNNAMED], typed_by_you: [], ...CREDIT };
  requests: Recorded[] = [];
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
        const label = suggest(body.query)[body.index];
        Object.assign(s, { address: label, place_name: label, time_zone: "America/Toronto" });
        return json(200, this.saved());
      }
      case "PUT /api/settings/methods":
        Object.assign(s, { method: body.method, asr_method: body.asr_method });
        return json(200, this.saved());
      case "GET /api/masjids/nearby":
        return json(200, this.nearby);
      case "PUT /api/settings/main-masjid": {
        if (body.choice === "home") {
          Object.assign(s, { main_masjid_choice: "home", main_masjid: null, main_masjid_short_name: null });
        } else {
          const masjid: Masjid =
            body.choice === "custom"
              ? { ...KMA, id: "44444444-4444-4444-4444-444444444444", name: body.name, address: body.address, source: "user", distance_km: null }
              : [...this.nearby.masjids, ...this.nearby.typed_by_you].find((m) => m.id === body.masjid_id)!;
          if (body.choice === "custom") this.nearby.typed_by_you = [masjid];
          Object.assign(s, { main_masjid_choice: "masjid", main_masjid: masjid, main_masjid_short_name: body.short_name ?? null });
        }
        return json(200, this.saved(updated(20)));
      }
      case "PUT /api/settings/weekly":
        s.weekly = body.days;
        return json(200, this.saved(updated(2)));
      case "PUT /api/settings/jumuah":
        s.jumuah_saved = true;
        s.jumuah_masjids = [...this.nearby.masjids, ...this.nearby.typed_by_you].filter((m) => body.masjid_ids.includes(m.id));
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

function updated(sent: number) {
  return { status: "updated", sent, waiting: 0, message: `Calendar updated. ${sent} events sent to Google.` };
}
