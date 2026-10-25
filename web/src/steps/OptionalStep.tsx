// Question 4, which can be skipped: how early to arrive before iqamah, a
// short name for the masjid in event titles, and colours for prayer and
// drive blocks. Skip saves the defaults: 5 minutes early, the full name,
// and Basil for both colours. Nothing goes to Google Calendar until this
// step is saved or skipped: setup's first calendar update comes after it.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { ColourPicker } from "../ColourPicker";
import { DEFAULT_ARRIVE_EARLY, DEFAULT_COLOUR } from "../labels";
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

const MAX_EARLY = 60;
const DEFAULTS: OptionalAnswers = {
  arrive_early_minutes: DEFAULT_ARRIVE_EARLY,
  prayer_color_id: DEFAULT_COLOUR,
  drive_color_id: DEFAULT_COLOUR,
};
const EARLY_ERROR = `Enter a whole number of minutes from 0 to ${MAX_EARLY}.`;

// "5" -> 5. Anything that isn't a whole number from 0 to 60 is null.
function wholeMinutes(text: string): number | null {
  if (!/^\d{1,2}$/.test(text.trim())) return null;
  const minutes = Number(text.trim());
  return minutes <= MAX_EARLY ? minutes : null;
}

export function OptionalStep({ settings, page = false, submitLabel = "Save", canSkip = false, onSaved, onCancel }: Props) {
  // Not answered yet: start from the defaults. Answered before: show what was saved.
  const fresh = settings.missing.includes("optional");
  const [early, setEarly] = useState(String(fresh ? DEFAULT_ARRIVE_EARLY : settings.arrive_early_minutes));
  const [earlyError, setEarlyError] = useState("");
  const [shortName, setShortName] = useState(settings.main_masjid_short_name ?? "");
  const [prayerColour, setPrayerColour] = useState(fresh ? DEFAULT_COLOUR : settings.prayer_color_id);
  const [driveColour, setDriveColour] = useState(fresh ? DEFAULT_COLOUR : settings.drive_color_id);
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
    const minutes = wholeMinutes(early);
    if (minutes === null) {
      setEarlyError(EARLY_ERROR);
      return;
    }
    setEarlyError("");
    void run({
      arrive_early_minutes: minutes,
      short_name: masjid ? shortName.trim() || undefined : undefined,
      prayer_color_id: prayerColour,
      drive_color_id: driveColour,
    });
  }

  return (
    // noValidate: the page shows its own message instead of the browser's bubble.
    <form onSubmit={save} aria-labelledby="optional-title" noValidate>
      <div className="step-top">
        <Heading id="optional-title">A few extras</Heading>
        {canSkip && (
          <button type="button" className="link skip" onClick={() => void run(DEFAULTS)} disabled={busy}>
            Skip
          </button>
        )}
      </div>

      <label htmlFor="arrive-early">How early do you want to arrive before iqamah?</label>
      <div className="minutes-field">
        <input
          id="arrive-early"
          type="number"
          inputMode="numeric"
          min={0}
          max={MAX_EARLY}
          step={1}
          value={early}
          onChange={(e) => setEarly(e.target.value)}
          aria-invalid={earlyError ? true : undefined}
          aria-describedby={earlyError ? "arrive-early-error" : undefined}
        />
        <span aria-hidden="true">minutes</span>
      </div>
      {earlyError && (
        <p className="error field-error" id="arrive-early-error" role="alert">
          {earlyError}
        </p>
      )}

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

      <div className="colour-row">
        <ColourPicker label="Prayer colour" value={prayerColour} onChange={setPrayerColour} />
        <ColourPicker label="Commute colour" value={driveColour} onChange={setDriveColour} />
      </div>

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
      </div>
    </form>
  );
}
