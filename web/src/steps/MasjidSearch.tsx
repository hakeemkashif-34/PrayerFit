// The masjid search box: masjids from Photon as the user types, closest
// to home first, each with its distance. A masjid that isn't on the map
// can be found by typing its address.

import { useState } from "react";
import { api, ApiError } from "../api";
import { SuggestBox } from "../SuggestBox";
import type { Masjid, MasjidSuggestion } from "../types";

type Props = {
  onPicked: (masjid: Masjid) => void;
  placeholder?: string;
  // Setup shows the box before a location is picked, but it can't search until then.
  disabled?: boolean;
};

export function MasjidSearch({ onPicked, placeholder = "Start typing the masjid's name", disabled = false }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function pick(suggestion: MasjidSuggestion, query: string) {
    setSaving(true);
    setError("");
    try {
      onPicked(await api.masjidFromSuggestion(query, suggestion.index));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't pick that masjid. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <SuggestBox<MasjidSuggestion>
        label="Masjid"
        placeholder={placeholder}
        search={async (query, signal) => (await api.suggestMasjids(query, signal)).suggestions}
        renderOption={(s) => (
          <span className="option">
            <strong>{s.label}</strong>
            <small>
              {s.kind === "address" ? "Address · " : ""}
              {s.distance_km} km away
              {s.detail ? ` · ${s.detail}` : ""}
            </small>
          </span>
        )}
        optionName={(s) => `${s.label}, ${s.distance_km} km away`}
        onPick={pick}
        emptyText="No masjids found. Try its address instead."
        disabled={saving || disabled}
      />
      <p className="hint small-line">Can't find it? Type its address.</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
