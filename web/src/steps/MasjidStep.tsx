// Question 2: "Which masjid do you usually go to?" A search box like the
// location step (see MasjidSearch), and a small "Skip" link. Skipping
// means every prayer is at home. The short name is in the optional step.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { distanceText, masjidName } from "../labels";
import type { Masjid, SaveResponse, Settings } from "../types";
import { MasjidSearch } from "./MasjidSearch";

type Props = {
  settings: Settings;
  // Show the question as the page's main heading (setup) or a card heading (settings).
  page?: boolean;
  submitLabel?: string;
  // Setup says "Skip". The settings page says "I pray at home".
  skipLabel?: string;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

export function MasjidStep({ settings, page = false, submitLabel = "Save", skipLabel = "Skip", onSaved, onCancel }: Props) {
  const [picked, setPicked] = useState<Masjid | null>(settings.main_masjid);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const Heading = page ? "h1" : "h2";

  async function run(save: () => Promise<SaveResponse>) {
    setBusy(true);
    setError("");
    try {
      onSaved(await save());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    if (!picked) return;
    void run(() => api.saveMainMasjid({ choice: "masjid", masjid_id: picked.id }));
  }

  const skip = () => void run(() => api.saveMainMasjid({ choice: "home" }));

  return (
    <form onSubmit={save} aria-labelledby="masjid-title">
      <Heading id="masjid-title">Which masjid do you usually go to?</Heading>

      {picked ? (
        <div className="current picked-masjid">
          <p>
            <strong>{masjidName(picked)}</strong>
            {picked.distance_km !== null && <span className="hint"> · {distanceText(picked.distance_km)}</span>}
          </p>
          <button type="button" className="link" onClick={() => setPicked(null)} disabled={busy}>
            Change
          </button>
        </div>
      ) : (
        <MasjidSearch onPicked={setPicked} />
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy || !picked}>
          {busy ? "Saving…" : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button type="button" className="link skip" onClick={skip} disabled={busy}>
          {skipLabel}
        </button>
      </div>
    </form>
  );
}
