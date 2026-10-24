// Step 1: the address. It's only looked up when the button is pressed,
// never while typing, as Nominatim's usage policy asks.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { OsmCredit } from "../OsmCredit";
import type { FoundAddress, SaveResponse } from "../types";

type Props = {
  initial: string | null;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

export function AddressStep({ initial, onSaved, onCancel }: Props) {
  const [address, setAddress] = useState(initial ?? "");
  const [found, setFound] = useState<FoundAddress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function search(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setFound(await api.searchAddress(address));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't search. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveAddress(address));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="address-title">
      <h2 id="address-title">Your address</h2>
      <p className="hint">Prayer times depend on where you are. Your address is stored encrypted.</p>
      {found === null ? (
        <form onSubmit={search}>
          <label htmlFor="address">Address</label>
          <input
            id="address"
            autoComplete="street-address"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="200 Kanata Ave, Ottawa"
            required
            minLength={3}
            maxLength={300}
          />
          <div className="actions">
            <button type="submit" disabled={busy || address.trim().length < 3}>
              {busy ? "Searching…" : "Find address"}
            </button>
            {onCancel && (
              <button type="button" className="secondary" onClick={onCancel}>
                Cancel
              </button>
            )}
          </div>
        </form>
      ) : (
        <div className="found">
          <p>Is this the right place?</p>
          <p className="place" data-testid="found-place">
            {found.place_name}
          </p>
          <p className="hint">Time zone: {found.time_zone}</p>
          <div className="actions">
            <button type="button" onClick={confirm} disabled={busy}>
              {busy ? "Saving…" : "Yes, that's it"}
            </button>
            <button type="button" className="secondary" onClick={() => setFound(null)} disabled={busy}>
              Not this place
            </button>
          </div>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <OsmCredit />
    </section>
  );
}
