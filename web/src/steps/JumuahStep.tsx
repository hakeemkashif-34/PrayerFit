// Jumuah masjids, found with the same search box as the main masjid.
// Only on the settings page for now. They can pick more than one, or none.
// The order matters: when drive times are unknown, the first one is used.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { distanceText, masjidName } from "../labels";
import type { Masjid, SaveResponse, Settings } from "../types";
import { MasjidSearch } from "./MasjidSearch";

type Props = {
  settings: Settings;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

export function JumuahStep({ settings, onSaved, onCancel }: Props) {
  const [picked, setPicked] = useState<Masjid[]>(settings.jumuah_masjids);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function add(masjid: Masjid) {
    setPicked((current) => (current.some((m) => m.id === masjid.id) ? current : [...current, masjid]));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveJumuah(picked.map((m) => m.id)));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} aria-labelledby="jumuah-title">
      <h2 id="jumuah-title">Where can you go for Jumuah?</h2>
      <p className="hint">
        Your main masjid is added for you. Add every other masjid that works, your favourite first. Each Friday,
        your calendar picks the Jumuah with the shortest drive, then the earliest time.
      </p>
      {picked.length > 0 && (
        <ul className="plain picked-list">
          {picked.map((m) => (
            <li key={m.id}>
              <span>
                <strong>{masjidName(m)}</strong>
                {m.distance_km !== null && <span className="hint"> · {distanceText(m.distance_km)}</span>}
              </span>
              <button
                type="button"
                className="link"
                aria-label={`Remove ${masjidName(m)}`}
                onClick={() => setPicked((current) => current.filter((x) => x.id !== m.id))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <MasjidSearch onPicked={add} placeholder="Add a masjid" />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : picked.length === 0 ? "Save with no Jumuah masjid" : "Save"}
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
