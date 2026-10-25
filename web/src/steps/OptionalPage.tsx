// Setup page 2, "Optional": short name, how early for prayers and for
// Jumuah, the commute time to the main masjid, colours, and the Jumuah
// chooser. Every answer has a default, so Skip (top right) saves the
// defaults and finishes.
//
// Finish saves the commute time, the Jumuah pick, and the other answers,
// then App fills the calendar. Nothing goes to Google Calendar before that.
// Setup keeps this page mounted while the user goes Back, so nothing typed
// here is lost.

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { ColourPicker } from "../ColourPicker";
import { JumuahChooser } from "../JumuahChooser";
import {
  COMMUTE_ERROR, DEFAULT_ARRIVE_EARLY, DEFAULT_COLOUR, DEFAULT_JUMUAH_ARRIVE_EARLY, EARLY_ERROR, MAX_COMMUTE, MAX_EARLY,
  masjidName, wholeMinutes,
} from "../labels";
import { MinutesField } from "../MinutesField";
import type { ChoicesRequest, OptionalAnswers, Settings, SlotKey } from "../types";

type Props = {
  settings: Settings;
  // Only the page on screen asks for this Friday's Jumuah times.
  active: boolean;
  // Setup opens the Google Calendar tab here, inside the click, so the
  // browser allows it. onSaveFailed closes it again.
  onFinishClick: () => void;
  onSaveFailed: () => void;
  onSaved: (settings: Settings) => void;
};

const DEFAULTS: OptionalAnswers = {
  arrive_early_minutes: DEFAULT_ARRIVE_EARLY,
  jumuah_arrive_early_minutes: DEFAULT_JUMUAH_ARRIVE_EARLY,
  prayer_color_id: DEFAULT_COLOUR,
  drive_color_id: DEFAULT_COLOUR,
};

// Blank means OpenRouteService's estimate (null). Anything else must be 1 to 120.
function commuteMinutes(text: string): number | null | "bad" {
  if (text.trim() === "") return null;
  return wholeMinutes(text, 1, MAX_COMMUTE) ?? "bad";
}

export function OptionalPage({ settings, active, onFinishClick, onSaveFailed, onSaved }: Props) {
  const masjid = settings.main_masjid_choice === "masjid" ? settings.main_masjid : null;
  const hasJumuah = settings.jumuah_masjids.length > 0;
  const savedCommute = settings.commute_times.find((c) => c.masjid_id === masjid?.id)?.minutes ?? null;

  const [shortName, setShortName] = useState(settings.main_masjid_short_name ?? "");
  const [early, setEarly] = useState(String(DEFAULT_ARRIVE_EARLY));
  const [jumuahEarly, setJumuahEarly] = useState(String(DEFAULT_JUMUAH_ARRIVE_EARLY));
  const [commute, setCommute] = useState(savedCommute === null ? "" : String(savedCommute));
  const [prayerColour, setPrayerColour] = useState<string | null>(DEFAULT_COLOUR);
  const [commuteColour, setCommuteColour] = useState<string | null>(DEFAULT_COLOUR);
  const [pick, setPick] = useState<SlotKey | null>(settings.jumuah_pick);
  const [errors, setErrors] = useState({ early: "", jumuahEarly: "", commute: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // A different main masjid on page 1: its own short name and commute time.
  useEffect(() => {
    setShortName(settings.main_masjid_short_name ?? "");
    setCommute(savedCommute === null ? "" : String(savedCommute));
  }, [masjid?.id]);

  const shownName = shortName.trim() || masjid?.name || "the masjid";

  // What the chooser should show: the answers typed so far, if they're valid.
  const typedJumuahEarly = wholeMinutes(jumuahEarly, 0, MAX_EARLY);
  const typedCommute = commuteMinutes(commute);
  const overrides: ChoicesRequest = {
    ...(typedJumuahEarly !== null && { jumuah_arrive_early_minutes: typedJumuahEarly }),
    ...(masjid && typedCommute !== "bad" && { commute_minutes: { [masjid.id]: typedCommute } }),
  };

  async function run(save: () => Promise<Settings>) {
    setBusy(true);
    setError("");
    try {
      onSaved(await save());
    } catch (e) {
      onSaveFailed();
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  function skip() {
    onFinishClick();
    void run(async () => (await api.saveOptional(DEFAULTS)).settings);
  }

  function finish(event: FormEvent) {
    event.preventDefault();
    const minutes = wholeMinutes(early, 0, MAX_EARLY);
    const jumuahMinutes = hasJumuah ? typedJumuahEarly : DEFAULT_JUMUAH_ARRIVE_EARLY;
    const found = {
      early: minutes === null ? EARLY_ERROR : "",
      jumuahEarly: jumuahMinutes === null ? EARLY_ERROR : "",
      commute: masjid && typedCommute === "bad" ? COMMUTE_ERROR : "",
    };
    setErrors(found);
    if (minutes === null || jumuahMinutes === null || found.commute) return;

    onFinishClick();
    void run(async () => {
      if (masjid) await api.saveCommuteTimes([{ masjid_id: masjid.id, minutes: typedCommute as number | null }]);
      if (hasJumuah && pick) await api.saveJumuahPick(pick);
      const saved = await api.saveOptional({
        arrive_early_minutes: minutes,
        jumuah_arrive_early_minutes: jumuahMinutes,
        short_name: masjid ? shortName.trim() || undefined : undefined,
        prayer_color_id: prayerColour,
        drive_color_id: commuteColour,
      });
      return saved.settings;
    });
  }

  return (
    // noValidate: the page shows its own messages instead of the browser's bubbles.
    <form onSubmit={finish} aria-labelledby="optional-title" noValidate>
      <div className="step-top">
        <h1 id="optional-title">Optional</h1>
        <button type="button" className="link skip" onClick={skip} disabled={busy}>
          Skip
        </button>
      </div>

      {masjid && (
        <>
          <label htmlFor="short-name">Short name for {masjid.name ?? "your masjid"}</label>
          <input id="short-name" value={shortName} onChange={(e) => setShortName(e.target.value)} placeholder="KMA" maxLength={40} />
          <p className="hint small-line">
            {masjid.name
              ? `Events will say "Dhuhr at ${shownName}".`
              : `This masjid has no name on the map. Give it one so events say where, like "Dhuhr at KMA".`}
          </p>
        </>
      )}

      <MinutesField id="arrive-early" label="How early do you want to arrive before iqamah?" value={early}
        onChange={setEarly} error={errors.early} min={0} max={MAX_EARLY} />

      {hasJumuah && (
        <MinutesField id="jumuah-early" label="How early do you want to arrive before Jumuah?" value={jumuahEarly}
          onChange={setJumuahEarly} error={errors.jumuahEarly} min={0} max={MAX_EARLY} />
      )}

      {masjid && (
        <MinutesField id="commute-main" label={`Commute time to ${masjidName(masjid)}`} value={commute}
          onChange={setCommute} error={errors.commute} min={1} max={MAX_COMMUTE}
          hint="Leave it blank to use a driving estimate from OpenRouteService." />
      )}

      <div className="colour-row">
        <ColourPicker label="Prayer colour" value={prayerColour} onChange={setPrayerColour} />
        <ColourPicker label="Commute colour" value={commuteColour} onChange={setCommuteColour} />
      </div>

      {hasJumuah && active && <JumuahChooser overrides={overrides} selected={pick} onSelect={setPick} />}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Finish"}
        </button>
      </div>
    </form>
  );
}
