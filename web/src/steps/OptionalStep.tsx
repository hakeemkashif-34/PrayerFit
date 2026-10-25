// Question 4, which can be skipped: how early to arrive before iqamah, a
// short name for the masjid in event titles, and colours for prayer and
// drive blocks. Skip saves the defaults: 0 minutes, the full name, and the
// calendar's own colour.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { ColourPicker } from "../ColourPicker";
import type { OptionalAnswers, SaveResponse, Settings } from "../types";

type Props = {
  settings: Settings;
  // Show the question as the page's main heading (setup) or a card heading (settings).
  page?: boolean;
  submitLabel?: string;
  // Setup has a Skip button. The settings page has Cancel instead.
  canSkip?: boolean;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

const MINUTES = Array.from({ length: 31 }, (_, n) => n);
const DEFAULTS: OptionalAnswers = { arrive_early_minutes: 0, prayer_color_id: null, drive_color_id: null };

export function OptionalStep({ settings, page = false, submitLabel = "Save", canSkip = false, onSaved, onCancel }: Props) {
  const [early, setEarly] = useState(settings.arrive_early_minutes);
  const [shortName, setShortName] = useState(settings.main_masjid_short_name ?? "");
  const [prayerColour, setPrayerColour] = useState(settings.prayer_color_id);
  const [driveColour, setDriveColour] = useState(settings.drive_color_id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const Heading = page ? "h1" : "h2";
  const masjid = settings.main_masjid_choice === "masjid" ? settings.main_masjid : null;
  const shownName = shortName.trim() || masjid?.name || "the masjid";

  async function run(answers: OptionalAnswers) {
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveOptional(answers));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    void run({
      arrive_early_minutes: early,
      short_name: masjid ? shortName.trim() || undefined : undefined,
      prayer_color_id: prayerColour,
      drive_color_id: driveColour,
    });
  }

  return (
    <form onSubmit={save} aria-labelledby="optional-title">
      <Heading id="optional-title">A few extras</Heading>
      <p className="hint">All optional. You can change these later in Settings.</p>

      <label htmlFor="arrive-early">How early do you want to arrive before iqamah?</label>
      <select id="arrive-early" value={early} onChange={(e) => setEarly(Number(e.target.value))}>
        {MINUTES.map((n) => (
          <option key={n} value={n}>
            {n === 0 ? "On time (0 minutes)" : `${n} minute${n === 1 ? "" : "s"} early`}
          </option>
        ))}
      </select>
      <p className="hint small-line">The drive block before each masjid prayer ends this many minutes before iqamah.</p>

      {masjid && (
        <>
          <label htmlFor="short-name">Short name for {masjid.name ?? "your masjid"} (optional)</label>
          <input id="short-name" value={shortName} onChange={(e) => setShortName(e.target.value)} placeholder="KMA" maxLength={40} />
          <p className="hint small-line">
            {masjid.name
              ? `Events will say "Dhuhr at ${shownName}".`
              : `This masjid has no name on the map. Give it one so events say where, like "Dhuhr at KMA".`}
          </p>
        </>
      )}

      <div className="colour-row">
        <ColourPicker label="Prayer colour" value={prayerColour} onChange={setPrayerColour} />
        <ColourPicker label="Drive colour" value={driveColour} onChange={setDriveColour} />
      </div>
      <p className="hint small-line">Google Calendar's own colours. "Calendar colour" uses the Prayers calendar's colour.</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
        {canSkip && (
          <button type="button" className="link skip" onClick={() => void run(DEFAULTS)} disabled={busy}>
            Skip
          </button>
        )}
      </div>
    </form>
  );
}
