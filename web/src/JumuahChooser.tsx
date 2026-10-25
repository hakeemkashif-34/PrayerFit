// The Jumuah chooser: the coming Friday as a day view, with grey "Busy"
// blocks from the user's calendar and a card for each Jumuah slot. A card
// covers its whole window, from leaving home to the end of Jumuah. Green
// fits the calendar, grey clashes. A grey one can still be picked.
//
// The backend works out every window (POST /api/jumuah/choices), so the
// times here are the same ones the calendar would use. Answers the page
// hasn't saved yet (how early, commute times) are sent along, so the cards
// change as the user types.
//
// The day view is a CSS grid with one row per minute. Busy blocks and cards
// are placed on the same rows, so they line up by time. Rows can grow, so a
// card with more text than its height pushes the rows down for everything,
// and they still line up on a phone.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { fridayText, timeText } from "./labels";
import type { ChoicesRequest, JumuahChoices, JumuahSlot, SlotKey } from "./types";

type Props = {
  overrides: ChoicesRequest;
  selected: SlotKey | null;
  onSelect: (key: SlotKey) => void;
  // Setup shows nothing when there's nothing to choose. Settings says why.
  emptyText?: string;
  // h2 on the setup page, h4 inside a Settings editor.
  heading?: "h2" | "h4";
};

const MINUTE = 60_000;
const HALF_HOUR = 30 * MINUTE;
// Wait for a pause in typing before asking again.
const TYPING_PAUSE_MS = 400;

export const sameSlot = (a: SlotKey | null, b: SlotKey | null) =>
  a !== null && b !== null && a.masjid_id === b.masjid_id && a.order === b.order;

const ms = (iso: string) => new Date(iso).getTime();
const windowStart = (slot: JumuahSlot) => ms(slot.leave_at ?? slot.arrive_at);

// Slots whose windows overlap go side by side. Each gets the first column that's free by then.
function columns(slots: JumuahSlot[]): number[] {
  const freeAt: number[] = [];
  return slots.map((slot) => {
    let column = freeAt.findIndex((end) => end <= windowStart(slot));
    if (column === -1) column = freeAt.length;
    freeAt[column] = ms(slot.ends_at);
    return column;
  });
}

export function JumuahChooser({ overrides, selected, onSelect, emptyText, heading = "h2" }: Props) {
  const [choices, setChoices] = useState<JumuahChoices | null>(null);
  const [error, setError] = useState("");
  // Once the user picks a card, a new answer from the backend doesn't move their choice.
  const picked = useRef(false);
  const latest = useRef({ selected, onSelect });
  latest.current = { selected, onSelect };
  const key = JSON.stringify(overrides);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const answer = await api.jumuahChoices(overrides, controller.signal);
        setChoices(answer);
        setError("");
        const { selected: current, onSelect: select } = latest.current;
        const stillThere = answer.slots.some((s) => sameSlot(s, current));
        // Pre-select the user's pick, or the earliest that fits.
        if (answer.selected && (!picked.current || !stillThere)) select(answer.selected);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "Couldn't load this Friday's Jumuah times. Try again.");
      }
    }, choices === null ? 0 : TYPING_PAUSE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // overrides is compared by its text, so a new object with the same answers doesn't ask again.
  }, [key]);

  if (error && choices === null) return <p className="error" role="alert">{error}</p>;
  if (choices === null) return <p className="hint">Loading this Friday's Jumuah times…</p>;
  if (choices.slots.length === 0 || !choices.friday || !choices.time_zone) {
    return emptyText ? <p className="hint">{emptyText}</p> : null;
  }

  const zone = choices.time_zone;
  const slots = choices.slots;
  const lanes = columns(slots);
  const laneCount = Math.max(...lanes) + 1;
  // From the half hour before the first window to the half hour after the last one.
  const first = Math.floor(Math.min(...slots.map(windowStart)) / HALF_HOUR) * HALF_HOUR;
  const last = Math.ceil(Math.max(...slots.map((s) => ms(s.ends_at))) / HALF_HOUR) * HALF_HOUR;
  // Grid lines are 1-based. Column 1 holds the times, column 2 the busy blocks.
  const row = (time: number) => Math.round((Math.min(Math.max(time, first), last) - first) / MINUTE) + 1;
  const busy = choices.busy.filter((b) => ms(b.ends_at) > first && ms(b.starts_at) < last);
  const marks: number[] = [];
  for (let t = first; t <= last; t += HALF_HOUR) marks.push(t);

  const time = (iso: string) => timeText(iso, zone);
  const Heading = heading;

  return (
    <section className="chooser" aria-labelledby="chooser-title">
      <Heading id="chooser-title">Jumuah on {fridayText(choices.friday)}</Heading>
      <p className="hint">Green fits your calendar. Grey clashes, but you can still pick it.</p>
      {!choices.busy_checked && <p className="hint small-line">Your calendar's busy times couldn't be checked.</p>}
      {error && <p className="error" role="alert">{error}</p>}

      <div
        className="day-view"
        role="radiogroup"
        aria-label={`Jumuah slots on ${fridayText(choices.friday)}`}
        style={{
          gridTemplateColumns: `52px 40px repeat(${laneCount}, minmax(0, 1fr))`,
          // One more row than minutes, for the last time mark.
          gridTemplateRows: `repeat(${row(last)}, minmax(1.4px, auto))`,
        }}
      >
        {marks.map((t) => (
          <div key={`line-${t}`} className="day-line" style={{ gridRow: `${row(t)} / span 1`, gridColumn: "1 / -1" }}>
            <span className="day-time">{time(new Date(t).toISOString())}</span>
          </div>
        ))}

        {busy.map((b) => {
          const rows = `${row(ms(b.starts_at))} / ${row(ms(b.ends_at))}`;
          return [
            // The label in its own column, so cards never cover it.
            <div key={`busy-${b.starts_at}`} className="busy-block" style={{ gridRow: rows, gridColumn: "2 / span 1" }}>
              Busy
              <span className="visually-hidden">
                {" "}
                {time(b.starts_at)} to {time(b.ends_at)}
              </span>
            </div>,
            // A faint band behind the cards, so a clash shows where it overlaps.
            <div key={`band-${b.starts_at}`} className="busy-band" style={{ gridRow: rows, gridColumn: "3 / -1" }} aria-hidden="true" />,
          ];
        })}

        {slots.map((slot, i) => {
          const isSelected = sameSlot(slot, selected);
          const commute = slot.commute_minutes === null ? "Commute time unknown" : `${slot.commute_minutes} min commute`;
          return (
            <label
              key={`${slot.masjid_id}-${slot.order}`}
              className={`slot ${slot.fits ? "fits" : "clashes"}${isSelected ? " selected" : ""}`}
              style={{
                gridRow: `${row(windowStart(slot))} / ${row(ms(slot.ends_at))}`,
                gridColumn: `${lanes[i] + 3} / span 1`,
              }}
            >
              <input
                type="radio"
                name="jumuah-slot"
                className="visually-hidden"
                checked={isSelected}
                onChange={() => {
                  picked.current = true;
                  onSelect({ masjid_id: slot.masjid_id, order: slot.order });
                }}
              />
              <strong className="slot-name">{slot.masjid_label}</strong>
              <span>
                {slot.order_label} at {time(slot.starts_at)}
              </span>
              <span>{commute}</span>
              <span>
                {slot.leave_at ? `Leave ${time(slot.leave_at)}` : `Arrive ${time(slot.arrive_at)}`}, done {time(slot.ends_at)}
                {slot.length_estimated && <span className="visually-hidden"> (end time estimated)</span>}
              </span>
              <span className="slot-fit">{slot.fits ? "Fits" : "Clashes with your calendar"}</span>
            </label>
          );
        })}
      </div>
    </section>
  );
}
