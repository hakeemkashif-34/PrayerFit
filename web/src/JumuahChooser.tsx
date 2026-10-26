// The Jumuah chooser: "Generally speaking, which Jumuah would you like to
// attend?" shown as a Friday in a day calendar. Times run down the side
// from 11 AM to 4 PM. Each slot (1st, 2nd, 3rd) at the user's Jumuah
// masjids is a block at its real time, from when to leave home to the end
// of Jumuah. The rest of the day is greyed out. The user clicks a block to
// pick it. The times are this week's, only as an example: the pick is saved
// by order, not by time. Jumuah is always at the main masjid.
//
// It doesn't show the user's busy times. Every Friday, the calendar update
// still checks the pick against their calendar.
//
// Blocks are placed by minute: top = minutes after the view's start, times
// 2px. Slots whose blocks overlap go side by side.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { hourText, minutesIntoDay, spanText, timeText } from "./labels";
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
const PX_PER_MINUTE = 2;

export const sameSlot = (a: SlotKey | null, b: SlotKey | null) =>
  a !== null && b !== null && a.masjid_id === b.masjid_id && a.order === b.order;

type Placed = { slot: JumuahSlot; leave: number; start: number; end: number; lane: number };

// Blocks that overlap (the 2nd leaving before the 1st ends) go side by side.
// Each gets the first lane that's free by then.
function place(slots: JumuahSlot[], zone: string): Placed[] {
  const freeAt: number[] = [];
  return slots.map((slot) => {
    const leave = minutesIntoDay(slot.leave_at, zone);
    const start = minutesIntoDay(slot.starts_at, zone);
    const end = minutesIntoDay(slot.ends_at, zone);
    let lane = freeAt.findIndex((free) => free <= leave);
    if (lane === -1) lane = freeAt.length;
    freeAt[lane] = end;
    return { slot, leave, start, end, lane };
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
  const placed = place(choices.slots, zone);
  const lanes = Math.max(...placed.map((p) => p.lane)) + 1;
  const viewStart = Math.min(VIEW_START, Math.floor(Math.min(...placed.map((p) => p.leave)) / 60) * 60);
  const viewEnd = Math.max(VIEW_END, Math.ceil(Math.max(...placed.map((p) => p.end)) / 60) * 60);
  const y = (minutes: number) => (minutes - viewStart) * PX_PER_MINUTE;
  const hours: number[] = [];
  for (let m = viewStart; m <= viewEnd; m += 60) hours.push(m);
  const time = (iso: string) => timeText(iso, zone);

  return (
    <section className="chooser" aria-labelledby="chooser-title">
      <Heading id="chooser-title">{QUESTION}</Heading>
      <p className="hint">
        This week's Friday, as an example. Each block runs from when you leave home to the end of Jumuah.
      </p>
      {notes}

      <div className="friday">
        <div className="friday-head" aria-hidden="true">Friday</div>
        <div className="friday-body" style={{ height: y(viewEnd) }}>
          {hours.map((m) => (
            <div key={m} className="friday-hour" style={{ top: y(m) }} aria-hidden="true">
              <span>{hourText(m)}</span>
            </div>
          ))}
          <div className="friday-day" role="radiogroup" aria-labelledby="chooser-title">
            {placed.map(({ slot, leave, start, end, lane }) => {
              const isSelected = sameSlot(slot, selected);
              const driving = start - leave;
              return (
                <label
                  key={`${slot.masjid_id}-${slot.order}`}
                  className={`friday-slot${isSelected ? " selected" : ""}`}
                  style={{
                    top: y(leave),
                    height: (end - leave) * PX_PER_MINUTE,
                    left: `calc(${(lane / lanes) * 100}% + 4px)`,
                    width: `calc(${100 / lanes}% - 8px)`,
                  }}
                >
                  <input
                    type="radio"
                    name="jumuah-slot"
                    className="visually-hidden"
                    checked={isSelected}
                    onChange={() => onSelect({ masjid_id: slot.masjid_id, order: slot.order })}
                  />
                  {driving > 0 && (
                    <span className="slot-leave" style={{ height: driving * PX_PER_MINUTE }}>
                      Leave {time(slot.leave_at)}
                    </span>
                  )}
                  <span className="slot-main">
                    <strong className="slot-name">{slot.masjid_label}</strong>
                    <span>{slot.order_label}</span>
                    <span>
                      {spanText(slot.starts_at, slot.ends_at, zone)}
                      {slot.length_estimated && <span className="visually-hidden"> (end time estimated)</span>}
                    </span>
                    {isSelected && <span className="slot-picked">✓ Selected</span>}
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
