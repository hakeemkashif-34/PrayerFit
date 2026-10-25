// Question 2: the main masjid, from OpenStreetMap masjids within 15 km
// (closest first and highlighted), "My masjid isn't listed", or "I pray at home".

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { masjidName } from "../labels";
import type { SaveResponse, Settings } from "../types";
import { useNearby } from "./useNearby";

type Props = {
  settings: Settings;
  // Show the question as the page's main heading (setup) or a card heading (settings).
  page?: boolean;
  submitLabel?: string;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

const CUSTOM = "custom";
const HOME = "home";

export function MasjidStep({ settings, page = false, submitLabel = "Save", onSaved, onCancel }: Props) {
  const Heading = page ? "h1" : "h2";
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

  // A short name belongs to one masjid, so picking another one clears it.
  function pick(value: string) {
    setChoice(value);
    setShortName(value === settings.main_masjid?.id ? (settings.main_masjid_short_name ?? "") : "");
  }

  const options = [...(nearby?.masjids ?? []), ...(nearby?.typed_by_you ?? [])];
  const atAMasjid = choice !== "" && choice !== HOME;
  const picked = options.find((m) => m.id === choice);
  const fullName = choice === CUSTOM ? customName.trim() || "your masjid" : picked ? masjidName(picked) : "your masjid";

  return (
    <form onSubmit={save} aria-labelledby="masjid-title">
      <Heading id="masjid-title">Here are the masjids closest to you. Which one do you go to?</Heading>
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
          <legend className="hint">Within {nearby.radius_km} km, closest first</legend>
          {nearby.masjids.length === 0 && <p className="hint">No masjids found on OpenStreetMap near you.</p>}
          {options.map((m, i) => (
            <label key={m.id} className={i === 0 && m.distance_km !== null ? "choice closest" : "choice"}>
              <input type="radio" name="masjid" value={m.id} checked={choice === m.id} onChange={() => pick(m.id)} />
              <span>
                {i === 0 && m.distance_km !== null && <span className="badge">Closest</span>}
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
            <input type="radio" name="masjid" value={CUSTOM} checked={choice === CUSTOM} onChange={() => pick(CUSTOM)} />
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
            <input type="radio" name="masjid" value={HOME} checked={choice === HOME} onChange={() => pick(HOME)} />
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
          <p className="hint">Events will say "Dhuhr at {shortName.trim() || fullName}".</p>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy || choice === ""}>
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
