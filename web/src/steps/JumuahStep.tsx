// Jumuah masjids, from the same nearby list. Only on the settings page for now.
// They can pick more than one, or none.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { masjidName } from "../labels";
import { OsmCredit } from "../OsmCredit";
import type { SaveResponse, Settings } from "../types";
import { useNearby } from "./useNearby";

type Props = {
  settings: Settings;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

export function JumuahStep({ settings, onSaved, onCancel }: Props) {
  const { nearby, error: loadError, retry } = useNearby();
  const [picked, setPicked] = useState<string[]>(settings.jumuah_masjids.map((m) => m.id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function toggle(id: string) {
    setPicked((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveJumuah(picked));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  const options = [...(nearby?.masjids ?? []), ...(nearby?.typed_by_you ?? [])];

  return (
    <form onSubmit={save} aria-labelledby="jumuah-title">
      <h2 id="jumuah-title">Where can you go for Jumuah?</h2>
      <p className="hint">Pick every masjid that works. A later update picks the Jumuah time that fits your Friday.</p>
      {loadError && (
        <p className="error" role="alert">
          {loadError}{" "}
          <button type="button" className="link" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {!nearby && !loadError && (
        <p className="hint" role="status">
          Searching for masjids nearby. This can take up to a minute.
        </p>
      )}
      {nearby && (
        <fieldset>
          <legend>Masjids within {nearby.radius_km} km</legend>
          {options.map((m) => (
            <label key={m.id} className="choice">
              <input type="checkbox" checked={picked.includes(m.id)} onChange={() => toggle(m.id)} />
              <span>
                <strong>{masjidName(m)}</strong>
                <small>{m.distance_km !== null ? `${m.distance_km} km away` : "Added by you"}</small>
                <small className="muted">{m.iqamah_status}</small>
              </span>
            </label>
          ))}
          {options.length === 0 && <p className="hint">No masjids found near you.</p>}
        </fieldset>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy || !nearby}>
          {busy ? "Saving…" : picked.length === 0 ? "Save with no Jumuah masjid" : "Save"}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      <OsmCredit />
    </form>
  );
}
