// Question 1: "What's your location?"
// Suggestions appear in a dropdown as the user types. To be fair to the
// free Photon service, the website only asks once typing stops for 400 ms,
// needs at least 3 characters, cancels a search that's no longer needed,
// and shows at most 5 suggestions. Picking one saves it.

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { api, ApiError } from "../api";
import type { LocationSuggestion, SaveResponse } from "../types";

export const TYPING_PAUSE_MS = 400;
const MIN_LENGTH = 3;

type Props = {
  // The saved place, if there is one.
  current: string | null;
  // Show the question as the page's main heading (setup) or a card heading (settings).
  page?: boolean;
  onSaved: (response: SaveResponse) => void;
  // Keep the saved place and move on (setup) or close the editor (settings).
  onKeep?: () => void;
  keepLabel?: string;
};

export function LocationStep({ current, page = false, onSaved, onKeep, keepLabel = "Keep this location" }: Props) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<LocationSuggestion[] | null>(null);
  // The text the suggestions are for. Picking sends this back, not whatever is typed now.
  const [resultsFor, setResultsFor] = useState("");
  const [active, setActive] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const Heading = page ? "h1" : "h2";

  useEffect(() => {
    const text = query.trim();
    if (text.length < MIN_LENGTH) {
      setSuggestions(null);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setSearching(true);
      setError("");
      try {
        const result = await api.suggestLocations(text, controller.signal);
        setSuggestions(result.suggestions);
        setResultsFor(text);
        setActive(-1);
      } catch (e) {
        if (controller.signal.aborted) return; // the user typed again
        setSuggestions(null);
        setError(e instanceof ApiError ? e.message : "Couldn't search. Try again.");
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, TYPING_PAUSE_MS);
    // Typing again cancels the wait, and the search if it already started.
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  async function pick(suggestion: LocationSuggestion) {
    setSaving(true);
    setError("");
    try {
      onSaved(await api.saveLocation(resultsFor, suggestion.index));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setSaving(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!suggestions?.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (i + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      void pick(suggestions[active]);
    } else if (event.key === "Escape") {
      setSuggestions(null);
    }
  }

  const open = suggestions !== null && query.trim().length >= MIN_LENGTH;

  return (
    <section aria-labelledby="location-title">
      <Heading id="location-title">What's your location?</Heading>
      <p className="hint">Prayer times depend on where you are. Your address is stored encrypted.</p>
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
      <label htmlFor="location">{current ? "Or search for a new address" : "Start typing your address"}</label>
      <div className="combobox">
        <input
          id="location"
          ref={inputRef}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="200 Kanata Ave, Ottawa"
          maxLength={200}
          disabled={saving}
        />
        {open && (
          <ul id={listId} role="listbox" className="suggestions" aria-label="Suggested places">
            {suggestions.length === 0 && <li className="empty">No places found. Try adding the city.</li>}
            {suggestions.map((s, i) => (
              <li
                key={s.index}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "active" : undefined}
                // mousedown, so the input doesn't lose focus first.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => void pick(s)}
              >
                {s.label}
              </li>
            ))}
          </ul>
        )}
      </div>
      {searching && <p className="hint">Searching…</p>}
      {saving && <p className="hint">Saving…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <p className="credit">
        Search by Photon. Map data from{" "}
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
          © OpenStreetMap contributors
        </a>
      </p>
    </section>
  );
}
