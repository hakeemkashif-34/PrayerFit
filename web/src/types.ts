// The shapes the API sends back. They match the Pydantic models in backend/app/routers/.

export type Me = {
  email: string;
  google_sign_in_needed: boolean;
  calendar_access: boolean;
  setup_complete: boolean;
};

export type Masjid = {
  id: string;
  name: string | null;
  address: string | null;
  source: "openstreetmap" | "user";
  distance_km: number | null;
  iqamah_status: string;
};

export type Prayer = "fajr" | "dhuhr" | "asr" | "maghrib" | "isha";

export type WeekdayPrayers = { weekday: number } & Record<Prayer, boolean>;

export type Step = "address" | "methods" | "masjid" | "weekly" | "jumuah";

export type Settings = {
  setup_complete: boolean;
  missing: Step[];
  address: string | null;
  place_name: string | null;
  time_zone: string | null;
  method: string | null;
  asr_method: string | null;
  main_masjid_choice: "masjid" | "home" | null;
  main_masjid: Masjid | null;
  main_masjid_short_name: string | null;
  weekly: WeekdayPrayers[];
  jumuah_saved: boolean;
  jumuah_masjids: Masjid[];
};

export type CalendarUpdate = {
  status: "updated" | "waiting" | "sign_in_needed" | "not_set_up";
  sent: number;
  waiting: number;
  message: string;
};

export type SaveResponse = {
  settings: Settings;
  calendar: CalendarUpdate | null;
};

export type FoundAddress = {
  place_name: string;
  latitude: number;
  longitude: number;
  time_zone: string;
  credit: string;
  credit_url: string;
};

export type Nearby = {
  radius_km: number;
  masjids: Masjid[];
  typed_by_you: Masjid[];
  credit: string;
  credit_url: string;
};
