// The shapes the API sends back. They match the Pydantic models in backend/app/routers/.

export type Me = {
  email: string;
  google_sign_in_needed: boolean;
  calendar_access: boolean;
  // False for users who signed in before free/busy was asked for. Settings asks them to sign in again.
  busy_access: boolean;
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

// The setup questions the backend tracks, in order. "optional" can be skipped.
export type Step = "address" | "masjid" | "weekly" | "optional";
// Each item on the Settings page, edited on its own.
export type Editable =
  | "address" | "masjid" | "weekly"
  | "jumuah" | "jumuah_pick" | "short_name" | "early" | "jumuah_early" | "prayer_colour" | "drive_colour";

// A Jumuah slot: a masjid and its 1st, 2nd, or 3rd Jumuah.
export type SlotKey = { masjid_id: string; order: number };

export type Settings = {
  setup_complete: boolean;
  missing: Step[];
  address: string | null;
  place_name: string | null;
  time_zone: string | null;
  main_masjid_choice: "masjid" | "home" | null;
  main_masjid: Masjid | null;
  main_masjid_short_name: string | null;
  weekly: WeekdayPrayers[];
  jumuah_saved: boolean;
  // In the order the user listed them.
  jumuah_masjids: Masjid[];
  // The optional step. Colours are Google's event colour IDs, "1" to "11". null uses the calendar's colour.
  arrive_early_minutes: number;
  jumuah_arrive_early_minutes: number;
  // null means the earliest Jumuah that fits.
  jumuah_pick: SlotKey | null;
  prayer_color_id: string | null;
  drive_color_id: string | null;
};

export type OptionalAnswers = {
  arrive_early_minutes: number;
  jumuah_arrive_early_minutes: number;
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

// What the Jumuah chooser shows for the coming Friday. Times are ISO strings with an offset.
export type BusyTime = { starts_at: string; ends_at: string };

export type JumuahSlot = SlotKey & {
  masjid_label: string;
  order_label: string; // "1st Jumuah"
  starts_at: string;
  // null when the drive time is unknown.
  leave_at: string | null;
  arrive_at: string;
  ends_at: string;
  // OpenRouteService's driving estimate.
  drive_minutes: number | null;
  jumuah_minutes: number;
  length_estimated: boolean;
  fits: boolean;
};

export type JumuahChoices = {
  friday: string | null;
  time_zone: string | null;
  busy_checked: boolean;
  busy: BusyTime[];
  // Earliest first. Empty means there's nothing to choose.
  slots: JumuahSlot[];
  selected: SlotKey | null;
};

// Answers the optional page hasn't saved yet, so the chooser can show them.
export type ChoicesRequest = {
  jumuah_arrive_early_minutes?: number;
};
