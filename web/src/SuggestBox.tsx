// A text box that shows suggestions in a dropdown as the user types.
// Used for the location, the masjid, and Jumuah masjids.
// To be fair to the free Photon service behind it, it only searches once
// typing stops for 400 ms, needs at least 3 characters, and cancels a
// search that's no longer needed.

import { useEffect, useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { ApiError } from "./api";

export const TYPING_PAUSE_MS = 400;
const MIN_LENGTH = 3;

type Props<T extends { index: number }> = {
  // The box's name for screen readers, like "Address". Hidden on screen.
  label: string;
  placeholder: string;
  search: (query: string, signal: AbortSignal) => Promise<T[]>;
  // What each suggestion looks like, and its name for screen readers.
  renderOption: (item: T) => ReactNode;
  optionName: (item: T) => string;
  // Gets the suggestion and the text it was found for (the backend needs both).
  onPick: (item: T, query: string) => void;
  emptyText: string;
  disabled?: boolean;
};

export function SuggestBox<T extends { index: number }>(props: Props<T>) {
  const { label, placeholder, search, renderOption, optionName, onPick, emptyText, disabled = false } = props;
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<T[] | null>(null);
  // The text the suggestions are for. Picking sends this back, not whatever is typed now.
  const [resultsFor, setResultsFor] = useState("");
  const [active, setActive] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  const listId = `${id}-list`;

  useEffect(() => {
    const text = query.trim();
    if (text.length < MIN_LENGTH) {
      setItems(null);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setSearching(true);
      setError("");
      try {
        setItems(await search(text, controller.signal));
        setResultsFor(text);
        setActive(-1);
      } catch (e) {
        if (controller.signal.aborted) return; // the user typed again
        setItems(null);
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
    // search is a new function on every render, so it's left out on purpose.
  }, [query]);

  function pick(item: T) {
    setItems(null);
    onPick(item, resultsFor);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!items?.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (i + 1) % items.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (i <= 0 ? items.length - 1 : i - 1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      pick(items[active]);
    } else if (event.key === "Escape") {
      setItems(null);
    }
  }

  const open = items !== null && query.trim().length >= MIN_LENGTH;

  return (
    <div className="suggest-box">
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <div className="combobox">
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          maxLength={200}
          disabled={disabled}
        />
        {open && (
          <ul id={listId} role="listbox" className="suggestions" aria-label="Suggestions">
            {items.length === 0 && <li className="empty">{emptyText}</li>}
            {items.map((item, i) => (
              <li
                key={item.index}
                id={`${listId}-${i}`}
                role="option"
                aria-label={optionName(item)}
                aria-selected={i === active}
                className={i === active ? "active" : undefined}
                // mousedown, so the input doesn't lose focus first.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(item)}
              >
                {renderOption(item)}
              </li>
            ))}
          </ul>
        )}
      </div>
      {searching && <p className="hint">Searching…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
