// The Jumuah chooser: "Generally speaking, which Jumuah would you like to
// attend?" shown as a Friday in a day calendar. Times run down the side
// from 11 AM to 4 PM. Each slot (1st, 2nd, 3rd) at the main masjid is a
// block covering just the Jumuah, from its start to its end. The rest of
// the day is greyed out. The user clicks a block to pick it. The times are
// this week's, only as an example: the pick is saved by order, not by time.
//
// It doesn't show the user's busy times. Every Friday, the calendar update
// still checks the pick against their calendar.
//
// Blocks are placed by minute (1.2px a minute), all in 1 column. A block is
// never shorter than its 2 lines of text, so if that would make it reach the
// next one, the next one moves down to keep a small gap.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { hourText, minutesIntoDay, spanText } from "./labels";
import type { JumuahChoices, JumuahSlot, SlotKey } from "./types";

type Props = {
  // Setup asks about the main masjid before it's saved. Settings leaves this out to use the saved one.
  masjidId?: string;
  selected: SlotKey | null;
  onSelect: (key: SlotKey) => void;
  // How many slots there are, once known. Setup saves the 1st Jumuah when it's 0.
  onLoaded?: (count: number) => void;
  // Setup says the pick can be changed in Settings later. Settings doesn't.
  where?: "setup" | "settings";
  // h2 on the setup page, h4 inside a Settings editor.
  heading?: "h2" | "h4";
};

export const QUESTION = "Generally speaking, which Jumuah would you like to attend?";

// The usual view: 11 AM to 4 PM. It grows if a block starts earlier or ends later.
const VIEW_START = 11 * 60;
const VIEW_END = 16 * 60;
const PX_PER_MINUTE = 1.2;
// Tall enough for "1st Jumuah ✓" and "12:45 to 1:30 PM", so nothing is cut off.
const MIN_BLOCK_PX = 54;
const GAP_PX = 6;

export const sameSlot = (a: SlotKey | null, b: SlotKey | null) =>
  a !== null && b !== null && a.masjid_id === b.masjid_id && a.order === b.order;

type Placed = { slot: JumuahSlot; start: number; end: number; top: number; height: number };

// In time order, one above the other. Each block starts at its time, or just
// under the block before it if that one is still there.
function place(slots: JumuahSlot[], zone: string, y: (minutes: number) => number): Placed[] {
  let bottom = -Infinity;
  return slots
    .map((slot) => ({ slot, start: minutesIntoDay(slot.starts_at, zone), end: minutesIntoDay(slot.ends_at, zone) }))
    .sort((a, b) => a.start - b.start)
    .map(({ slot, start, end }) => {
      const top = Math.max(y(start), bottom + GAP_PX);
      const height = Math.max(MIN_BLOCK_PX, (end - start) * PX_PER_MINUTE);
      bottom = top + height;
      return { slot, start, end, top, height };
    });
}

export function noTimesText(name: string, where: "setup" | "settings"): string {
  const base = `Jumuah times for ${name} aren't available yet.`;
  return where === "setup" ? `${base} We'll use the 1st Jumuah, and you can change it in Settings later.` : base;
}

export function JumuahChooser({ masjidId, selected, onSelect, onLoaded, where = "setup", heading = "h2" }: Props) {
  const [choices, setChoices] = useState<JumuahChoices | null>(null);
  const [error, setError] = useState("");
  const latest = useRef({ selected, onSelect, onLoaded });
  latest.current = { selected, onSelect, onLoaded };
  const key = masjidId ?? "";

  useEffect(() => {
    const controller = new AbortController();
    setChoices(null);
    api
      .jumuahSlots(masjidId, controller.signal)
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
  }, [key]);

  const Heading = heading;
  if (error) return <p className="error" role="alert">{error}</p>;
  if (choices === null) return <p className="hint">Loading the Jumuah times…</p>;
  if (choices.slots.length === 0 && choices.no_times.length === 0) return null;

  const notes = choices.no_times.map((name) => (
    <p key={name} className="notice">{noTimesText(name, choices.slots.length === 0 ? where : "settings")}</p>
  ));
  if (choices.slots.length === 0) {
    return (
      <section className="chooser" aria-labelledby="chooser-title">
        <Heading id="chooser-title">{QUESTION}</Heading>
        {notes}
      </section>
    );
  }

  const zone = choices.time_zone;
  const starts = choices.slots.map((s) => minutesIntoDay(s.starts_at, zone));
  const ends = choices.slots.map((s) => minutesIntoDay(s.ends_at, zone));
  const viewStart = Math.min(VIEW_START, Math.floor(Math.min(...starts) / 60) * 60);
  const viewEnd = Math.max(VIEW_END, Math.ceil(Math.max(...ends) / 60) * 60);
  const y = (minutes: number) => (minutes - viewStart) * PX_PER_MINUTE;
  const placed = place(choices.slots, zone, y);
  const hours: number[] = [];
  for (let m = viewStart; m <= viewEnd; m += 60) hours.push(m);
  // A block moved down could reach past 4 PM, so the day grows to fit it.
  const height = Math.max(y(viewEnd), ...placed.map((p) => p.top + p.height));

  return (
    <section className="chooser" aria-labelledby="chooser-title">
      <Heading id="chooser-title">{QUESTION}</Heading>
      <p className="hint">This week's Friday, as an example.</p>
      {notes}

      <div className="friday">
        <div className="friday-head" aria-hidden="true">Friday</div>
        <div className="friday-body" style={{ height }}>
          {hours.map((m) => (
            <div key={m} className="friday-hour" style={{ top: y(m) }} aria-hidden="true">
              <span>{hourText(m)}</span>
            </div>
          ))}
          <div className="friday-day" role="radiogroup" aria-labelledby="chooser-title">
            {placed.map(({ slot, top, height: blockHeight }) => {
              const isSelected = sameSlot(slot, selected);
              return (
                <label
                  key={`${slot.masjid_id}-${slot.order}`}
                  className={`friday-slot${isSelected ? " selected" : ""}`}
                  style={{ top, height: blockHeight }}
                >
                  <input
                    type="radio"
                    name="jumuah-slot"
                    className="visually-hidden"
                    checked={isSelected}
                    onChange={() => onSelect({ masjid_id: slot.masjid_id, order: slot.order })}
                  />
                  <span className="slot-main">
                    <strong className="slot-name">
                      {slot.order_label}
                      {isSelected && <span className="slot-picked" aria-hidden="true"> ✓</span>}
                    </strong>
                    <span>
                      {spanText(slot.starts_at, slot.ends_at, zone)}
                      {slot.length_estimated && <span className="visually-hidden"> (end time estimated)</span>}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
