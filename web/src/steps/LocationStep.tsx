// Question 1: "What's your location?" Suggestions come from Photon as the
// user types (see SuggestBox). Picking one saves it.

import { useState } from "react";
import { api, ApiError } from "../api";
import { SuggestBox } from "../SuggestBox";
import type { LocationSuggestion, SaveResponse } from "../types";

type Props = {
  // The saved place, if there is one.
  current: string | null;
  // Show the question as the page's main heading (setup) or a card heading (settings).
  page?: boolean;
  onSaved: (response: SaveResponse) => void;
  // Keep the saved place and move on (setup) or close the editor (settings).
  onKeep?: () => void;
  keepLabel?: string;
  // A line under the question, like "e.g. 24 Maple Drive, Ottawa".
  example?: string;
};

export function LocationStep({ current, page = false, onSaved, onKeep, keepLabel = "Keep this location", example }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const Heading = page ? "h1" : "h2";

  async function pick(suggestion: LocationSuggestion, query: string) {
    setSaving(true);
    setError("");
    try {
      onSaved(await api.saveLocation(query, suggestion.index));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="location-title">
      <Heading id="location-title">What's your location?</Heading>
      {example && <p className="hint example">{example}</p>}
      {current && (
        <div className="current">
          <p>
            Saved: <strong>{current}</strong>
          </p>
          {onKeep && (
            <button type="button" className="secondary" onClick={onKeep} disabled={saving}>
              {keepLabel}
            </button>
          )}
        </div>
      )}
      <SuggestBox<LocationSuggestion>
        label="Address"
        placeholder={current ? "Search for a new address" : "Start typing your address"}
        search={async (query, signal) => (await api.suggestLocations(query, signal)).suggestions}
        renderOption={(s) => s.label}
        optionName={(s) => s.label}
        onPick={pick}
        emptyText="No places found. Try adding the city."
        disabled={saving}
      />
      {saving && <p className="hint">Saving…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
