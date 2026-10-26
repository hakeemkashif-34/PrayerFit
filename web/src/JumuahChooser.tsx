// The Jumuah chooser: "Generally speaking, which Jumuah would you like to
// attend?" Each slot (1st, 2nd, 3rd) at the user's Jumuah masjids is a
// block on a simple midday calendar, from its start to its end (the
// masjid's Jumuah length). The times are this week's, only as an example:
// the pick is saved by order, not by time. The user clicks a block to pick it.
//
// It doesn't show a date or the user's busy times. Every Friday, the
// calendar update still checks the pick against their calendar.
//
// The view is a CSS grid with one row per minute, so blocks line up by
// time. Rows can grow, so a block with more text than its height pushes
// the rows down and everything still lines up on a phone.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { timeText } from "./labels";
import type { JumuahChoices, JumuahSlot, SlotKey } from "./types";

type Props = {
  // Setup asks about masjids it hasn't saved yet. Settings leaves this out to use the saved Jumuah masjids.
  masjidIds?: string[];
  selected: SlotKey | null;
  onSelect: (key: SlotKey) => void;
  // How many slots there are, once known. Setup skips the question when it's 0.
  onLoaded?: (count: number) => void;
  // Setup shows nothing when there's nothing to choose. Settings says why.
  emptyText?: string;
  // h2 on the setup page, h4 inside a Settings editor.
  heading?: "h2" | "h4";
};

export const QUESTION = "Generally speaking, which Jumuah would you like to attend?";

const MINUTE = 60_000;
const HALF_HOUR = 30 * MINUTE;

export const sameSlot = (a: SlotKey | null, b: SlotKey | null) =>
  a !== null && b !== null && a.masjid_id === b.masjid_id && a.order === b.order;

const ms = (iso: string) => new Date(iso).getTime();

// Slots that overlap go side by side. Each gets the first column that's free by then.
function columns(slots: JumuahSlot[]): number[] {
  const freeAt: number[] = [];
  return slots.map((slot) => {
    let column = freeAt.findIndex((end) => end <= ms(slot.starts_at));
    if (column === -1) column = freeAt.length;
    freeAt[column] = ms(slot.ends_at);
    return column;
  });
}

export function JumuahChooser({ masjidIds, selected, onSelect, onLoaded, emptyText, heading = "h2" }: Props) {
  const [choices, setChoices] = useState<JumuahChoices | null>(null);
  const [error, setError] = useState("");
  const latest = useRef({ selected, onSelect, onLoaded });
  latest.current = { selected, onSelect, onLoaded };
  const key = JSON.stringify(masjidIds ?? null);

  useEffect(() => {
    const controller = new AbortController();
    setChoices(null);
    api
      .jumuahSlots(masjidIds, controller.signal)
      .then((answer) => {
        setChoices(answer);
        setError("");
        const { selected: current, onSelect: select, onLoaded: loaded } = latest.current;
        // Keep the user's choice if it's still there. Otherwise pre-select the 1st Jumuah.
        if (answer.selected && !answer.slots.some((s) => sameSlot(s, current))) select(answer.selected);
        loaded?.(answer.slots.length);
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "Couldn't load the Jumuah times. Try again.");
        latest.current.onLoaded?.(0);
      });
    return () => controller.abort();
    // masjidIds is compared by its text, so a new array with the same IDs doesn't ask again.
  }, [key]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (choices === null) return <p className="hint">Loading the Jumuah times…</p>;
  if (choices.slots.length === 0) return emptyText ? <p className="hint">{emptyText}</p> : null;

  const zone = choices.time_zone;
  const slots = choices.slots;
  const lanes = columns(slots);
  const laneCount = Math.max(...lanes) + 1;
  // From the half hour before the first Jumuah to the half hour after the last one ends.
  const first = Math.floor(Math.min(...slots.map((s) => ms(s.starts_at))) / HALF_HOUR) * HALF_HOUR;
  const last = Math.ceil(Math.max(...slots.map((s) => ms(s.ends_at))) / HALF_HOUR) * HALF_HOUR;
  // Grid lines are 1-based. Column 1 holds the times.
  const row = (time: number) => Math.round((time - first) / MINUTE) + 1;
  const marks: number[] = [];
  for (let t = first; t <= last; t += HALF_HOUR) marks.push(t);
  const time = (iso: string) => timeText(iso, zone);
  const Heading = heading;

  return (
    <section className="chooser" aria-labelledby="chooser-title">
      <Heading id="chooser-title">{QUESTION}</Heading>
      <p className="hint">This week's times, as an example.</p>

      <div
        className="day-view"
        role="radiogroup"
        aria-labelledby="chooser-title"
        style={{
          gridTemplateColumns: `64px repeat(${laneCount}, minmax(0, 1fr))`,
          // One more row than minutes, for the last time mark.
          gridTemplateRows: `repeat(${row(last)}, minmax(1.4px, auto))`,
        }}
      >
        {marks.map((t) => (
          <div key={`line-${t}`} className="day-line" style={{ gridRow: `${row(t)} / span 1`, gridColumn: "1 / -1" }}>
            <span className="day-time">{time(new Date(t).toISOString())}</span>
          </div>
        ))}

        {slots.map((slot, i) => {
          const isSelected = sameSlot(slot, selected);
          return (
            <label
              key={`${slot.masjid_id}-${slot.order}`}
              className={`slot${isSelected ? " selected" : ""}`}
              style={{
                gridRow: `${row(ms(slot.starts_at))} / ${row(ms(slot.ends_at))}`,
                gridColumn: `${lanes[i] + 2} / span 1`,
              }}
            >
              <input
                type="radio"
                name="jumuah-slot"
                className="visually-hidden"
                checked={isSelected}
                onChange={() => onSelect({ masjid_id: slot.masjid_id, order: slot.order })}
              />
              <strong className="slot-name">{slot.masjid_label}</strong>
              <span>{slot.order_label}</span>
              <span>
                {time(slot.starts_at)} to {time(slot.ends_at)}
                {slot.length_estimated && <span className="visually-hidden"> (end time estimated)</span>}
              </span>
              {isSelected && <span className="slot-fit">Picked</span>}
            </label>
          );
        })}
      </div>
    </section>
  );
}
