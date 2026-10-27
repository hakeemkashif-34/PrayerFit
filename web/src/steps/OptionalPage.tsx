// Setup page 2, "Optional": short name, how early for prayers and for
// Jumuah, colours, and the 2 notifications. Every answer has a default, so
// Skip (top right) saves the defaults and finishes. The notifications are
// saved here, so the very first calendar already has them.
//
// Finish saves the answers,
// then App fills the calendar. Nothing goes to Google Calendar before that.
// Setup keeps this page mounted while the user goes Back, so nothing typed
// here is lost.

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { ColourPicker } from "../ColourPicker";
import {
  DEFAULT_ARRIVE_EARLY, DEFAULT_COLOUR, DEFAULT_JUMUAH_ARRIVE_EARLY, DEFAULT_REMINDER, EARLY_ERROR, LABELS, MAX_EARLY,
  QUESTIONS, REMINDER_HINT, wholeMinutes,
} from "../labels";
import { MinutesField } from "../MinutesField";
import type { OptionalAnswers, Settings } from "../types";

type Props = {
  settings: Settings;
  // Setup opens the Google Calendar tab here, inside the click, so the
  // browser allows it. onSaveFailed closes it again.
  // colourId: the prayer colour picked, for the new tab's little calendar.
  onFinishClick: (colourId: string | null) => void;
  onSaveFailed: () => void;
  onSaved: (settings: Settings) => void;
};

const DEFAULTS: OptionalAnswers = {
  arrive_early_minutes: DEFAULT_ARRIVE_EARLY,
  jumuah_arrive_early_minutes: DEFAULT_JUMUAH_ARRIVE_EARLY,
  prayer_color_id: DEFAULT_COLOUR,
  drive_color_id: DEFAULT_COLOUR,
  leave_reminder_minutes: DEFAULT_REMINDER,
  home_reminder_minutes: DEFAULT_REMINDER,
};

export function OptionalPage({ settings, onFinishClick, onSaveFailed, onSaved }: Props) {
  const masjid = settings.main_masjid_choice === "masjid" ? settings.main_masjid : null;
  // Jumuah is always at the main masjid, so praying at home means no Jumuah.
  const hasJumuah = masjid !== null;

  const [shortName, setShortName] = useState(settings.main_masjid_short_name ?? "");
  const [early, setEarly] = useState(String(DEFAULT_ARRIVE_EARLY));
  const [jumuahEarly, setJumuahEarly] = useState(String(DEFAULT_JUMUAH_ARRIVE_EARLY));
  const [prayerColour, setPrayerColour] = useState<string | null>(DEFAULT_COLOUR);
  const [driveColour, setDriveColour] = useState<string | null>(DEFAULT_COLOUR);
  const [leaveReminder, setLeaveReminder] = useState(String(DEFAULT_REMINDER));
  const [homeReminder, setHomeReminder] = useState(String(DEFAULT_REMINDER));
  const [errors, setErrors] = useState({ early: "", jumuahEarly: "", leave: "", home: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // A different main masjid on page 1: its own short name.
  useEffect(() => {
    setShortName(settings.main_masjid_short_name ?? "");
  }, [masjid?.id]);

  const shownName = shortName.trim() || masjid?.name || "the masjid";


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
    onFinishClick(DEFAULTS.prayer_color_id);
    void run(async () => (await api.saveOptional(DEFAULTS)).settings);
  }

  function finish(event: FormEvent) {
    event.preventDefault();
    const minutes = wholeMinutes(early, 0, MAX_EARLY);
    const jumuahMinutes = hasJumuah ? wholeMinutes(jumuahEarly, 0, MAX_EARLY) : DEFAULT_JUMUAH_ARRIVE_EARLY;
    const leave = wholeMinutes(leaveReminder, 0, MAX_EARLY);
    const home = wholeMinutes(homeReminder, 0, MAX_EARLY);
    const found = {
      early: minutes === null ? EARLY_ERROR : "",
      jumuahEarly: jumuahMinutes === null ? EARLY_ERROR : "",
      leave: leave === null ? EARLY_ERROR : "",
      home: home === null ? EARLY_ERROR : "",
    };
    setErrors(found);
    if (minutes === null || jumuahMinutes === null || leave === null || home === null) return;

    onFinishClick(prayerColour);
    void run(async () => {
      const saved = await api.saveOptional({
        arrive_early_minutes: minutes,
        jumuah_arrive_early_minutes: jumuahMinutes,
        short_name: masjid ? shortName.trim() || undefined : undefined,
        prayer_color_id: prayerColour,
        drive_color_id: driveColour,
        leave_reminder_minutes: leave,
        home_reminder_minutes: home,
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

      <MinutesField id="arrive-early" label={QUESTIONS.early} value={early}
        onChange={setEarly} error={errors.early} min={0} max={MAX_EARLY} />

      {hasJumuah && (
        <MinutesField id="jumuah-early" label={QUESTIONS.jumuahEarly} value={jumuahEarly}
          onChange={setJumuahEarly} error={errors.jumuahEarly} min={0} max={MAX_EARLY} />
      )}

      <div className="colour-row">
        <ColourPicker label="Prayer colour" value={prayerColour} onChange={setPrayerColour} />
        <ColourPicker label="Drive colour" value={driveColour} onChange={setDriveColour} />
      </div>

      {/* The same labels, boxes, and defaults as Settings. 0 means no notification. */}
      <MinutesField id="leave-reminder" label={LABELS.leaveReminder} value={leaveReminder} onChange={setLeaveReminder}
        error={errors.leave} min={0} max={MAX_EARLY} hint={REMINDER_HINT} />
      <MinutesField id="home-reminder" label={LABELS.homeReminder} value={homeReminder} onChange={setHomeReminder}
        error={errors.home} min={0} max={MAX_EARLY} hint={REMINDER_HINT} />

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
