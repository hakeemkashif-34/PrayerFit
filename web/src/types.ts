// The shapes the API sends back. They match the Pydantic models in backend/app/routers/.

export type Me = {
  email: string;
  google_sign_in_needed: boolean;
  calendar_access: boolean;
  setup_complete: boolean;
};

export type Masjid = {
  id: string;
  // Empty for a masjid picked by its address.
  name: string | null;
  address: string | null;
  // "user" means picked by its address.
  source: "openstreetmap" | "user";
  distance_km: number | null;
  // Where its times come from, like "Times from MAWAQIT, updated Oct 25, 2026".
  iqamah_status: string;
};

export type Prayer = "fajr" | "dhuhr" | "asr" | "maghrib" | "isha";

export type WeekdayPrayers = { weekday: number } & Record<Prayer, boolean>;

// The 4 setup questions, in order. "optional" can be skipped.
export type Step = "address" | "masjid" | "weekly" | "optional";
// Everything the settings page can edit. Methods and Jumuah aren't in setup for now.
export type Editable = Step | "methods" | "jumuah";

export type Settings = {
  setup_complete: boolean;
  missing: Step[];
  address: string | null;
  place_name: string | null;
  time_zone: string | null;
  // The defaults (isna, standard) until the user picks others.
  method: string;
  asr_method: string;
  main_masjid_choice: "masjid" | "home" | null;
  main_masjid: Masjid | null;
  main_masjid_short_name: string | null;
  weekly: WeekdayPrayers[];
  jumuah_saved: boolean;
  // In the order the user listed them.
  jumuah_masjids: Masjid[];
  // The optional step. Colours are Google's event colour IDs, "1" to "11". null uses the calendar's colour.
  arrive_early_minutes: number;
  prayer_color_id: string | null;
  drive_color_id: string | null;
};

export type OptionalAnswers = {
  arrive_early_minutes: number;
  short_name?: string;
  prayer_color_id: string | null;
  drive_color_id: string | null;
};

export type CalendarUpdate = {
  // "adding" is the website's own, while setup's first update runs.
  status: "updated" | "waiting" | "sign_in_needed" | "not_set_up" | "adding";
  sent: number;
  waiting: number;
  message: string;
};

export type SaveResponse = {
  settings: Settings;
  calendar: CalendarUpdate | null;
};

export type LocationSuggestion = {
  index: number;
  label: string;
};

export type Suggestions = {
  suggestions: LocationSuggestion[];
  credit: string;
  credit_url: string;
};

export type MasjidSuggestion = {
  index: number;
  // "masjid" is a place of worship on OpenStreetMap. "address" is for one that isn't.
  kind: "masjid" | "address";
  label: string;
  detail: string | null;
  distance_km: number;
};
