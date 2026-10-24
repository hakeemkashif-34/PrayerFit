// Step 3: the main masjid, from OpenStreetMap masjids within 15 km,
// "My masjid isn't listed", or "I pray at home".

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

const CUSTOM = "custom";
const HOME = "home";

export function MasjidStep({ settings, onSaved, onCancel }: Props) {
  const { nearby, error: loadError, retry } = useNearby();
  const [choice, setChoice] = useState(
    settings.main_masjid_choice === "home" ? HOME : (settings.main_masjid?.id ?? ""),
  );
  const [shortName, setShortName] = useState(settings.main_masjid_short_name ?? "");
  const [customName, setCustomName] = useState("");
  const [customAddress, setCustomAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const short_name = shortName.trim() || undefined;
      if (choice === HOME) onSaved(await api.saveMainMasjid({ choice: "home" }));
      else if (choice === CUSTOM)
        onSaved(await api.saveMainMasjid({ choice: "custom", name: customName, address: customAddress, short_name }));
      else onSaved(await api.saveMainMasjid({ choice: "masjid", masjid_id: choice, short_name }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  const options = [...(nearby?.masjids ?? []), ...(nearby?.typed_by_you ?? [])];
  const atAMasjid = choice !== "" && choice !== HOME;

  return (
    <form onSubmit={save} aria-labelledby="masjid-title">
      <h2 id="masjid-title">Your main masjid</h2>
      {loadError && (
        <p className="error" role="alert">
          {loadError}{" "}
          <button type="button" className="link" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {!nearby && !loadError && <p className="hint">Finding masjids near you…</p>}
      {nearby && (
        <fieldset>
          <legend>Masjids within {nearby.radius_km} km, closest first</legend>
          {nearby.masjids.length === 0 && <p className="hint">No masjids found on OpenStreetMap near you.</p>}
          {options.map((m) => (
            <label key={m.id} className="choice">
              <input type="radio" name="masjid" value={m.id} checked={choice === m.id} onChange={() => setChoice(m.id)} />
              <span>
                <strong>{masjidName(m)}</strong>
                <small>
                  {m.distance_km !== null ? `${m.distance_km} km away` : "Added by you"}
                  {m.address ? ` · ${m.address}` : ""}
                </small>
                <small className="muted">{m.iqamah_status}</small>
              </span>
            </label>
          ))}
          <label className="choice">
            <input type="radio" name="masjid" value={CUSTOM} checked={choice === CUSTOM} onChange={() => setChoice(CUSTOM)} />
            <span>
              <strong>My masjid isn't listed</strong>
            </span>
          </label>
          {choice === CUSTOM && (
            <div className="indent">
              <label htmlFor="custom-name">Masjid name</label>
              <input id="custom-name" value={customName} onChange={(e) => setCustomName(e.target.value)} required maxLength={200} />
              <label htmlFor="custom-address">Masjid address</label>
              <input id="custom-address" value={customAddress} onChange={(e) => setCustomAddress(e.target.value)} required maxLength={300} />
            </div>
          )}
          <label className="choice">
            <input type="radio" name="masjid" value={HOME} checked={choice === HOME} onChange={() => setChoice(HOME)} />
            <span>
              <strong>I pray at home</strong>
            </span>
          </label>
        </fieldset>
      )}
      {atAMasjid && (
        <div>
          <label htmlFor="short-name">Short name for your calendar (optional)</label>
          <input
            id="short-name"
            value={shortName}
            onChange={(e) => setShortName(e.target.value)}
            placeholder="KMA"
            maxLength={40}
          />
          <p className="hint">Events will say "Dhuhr at {shortName.trim() || "the masjid's name"}".</p>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy || choice === ""}>
          {busy ? "Saving…" : "Save"}
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
