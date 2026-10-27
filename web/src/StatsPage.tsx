// The private /stats page: a graph of total users over time, and how many
// users picked each masjid. Only the ADMIN_EMAIL account can open it. The
// API answers 404 for everyone else, so this page just says "Page not
// found", the same as any page that doesn't exist. Nothing links here.
//
// Counts only. No emails, names, or addresses are ever sent.

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api, ApiError } from "./api";
import { timeText } from "./labels";
import type { GraphRange, Stats, UsersGraph } from "./types";

// Every time on this page is Toronto time, the same as the backend's days.
const TIME_ZONE = "America/Toronto";

// Checked with the dataviz palette validator on white.
const LINE = "#1f8a52";

// The card sits in the band above the plot, so it never covers the line.
// The value labels go on the right, like YouTube Studio's graphs.
const H = 300;
// The left side has room for half a date, so the first one can sit centred under its point.
const PAD = { top: 76, right: 48, bottom: 32, left: 22 };
// The bottom labels are 11px, about 6.2px a character ("Oct 20" measured 36px). They also need a small gap.
const CHAR_WIDTH = 6.2;
const LABEL_GAP = 6;
// Steps between bottom labels: round clock hours, or whole days.
const STRIDES = { hour: [1, 2, 3, 4, 6, 8, 12, 24], day: [1, 2, 3, 5, 7, 10, 14, 15, 21, 30, 45, 60, 90, 120, 180, 365] };

const RANGES: { value: GraphRange; label: string }[] = [
  { value: "1d", label: "1 day" },
  { value: "2d", label: "2 days" },
  { value: "3d", label: "3 days" },
  { value: "5d", label: "5 days" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "all", label: "All time" },
];

// "Oct 26"
function dayText(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { month: "short", day: "numeric", timeZone: TIME_ZONE });
}

// "Oct 26" for a day, "Oct 26, 2:00 PM" for an hour.
function pointText(iso: string, step: UsersGraph["step"]): string {
  return step === "hour" ? `${dayText(iso)}, ${timeText(iso, TIME_ZONE)}` : dayText(iso);
}

// The hour on Toronto's clock, 0 to 23.
function localHour(iso: string): number {
  return Number(new Intl.DateTimeFormat("en-CA", { hour: "numeric", hourCycle: "h23", timeZone: TIME_ZONE }).format(new Date(iso)));
}

// A bottom label: "2 PM" for an hour, "Oct 26" for a day. Midnight shows the date,
// so 2 or 3 days of hours still say which day is which.
function axisText(iso: string, step: UsersGraph["step"]): string {
  if (step === "day" || localHour(iso) === 0) return dayText(iso);
  return timeText(iso, TIME_ZONE).replace(":00", ""); // "2:00 PM" -> "2 PM"
}

// "1,234"
const count = (n: number) => n.toLocaleString("en-CA");

// "950", "1K", "1.5K", "1.25K"
function valueText(n: number): string {
  if (n < 1000) return String(n);
  return `${Number((n / 1000).toFixed(2))}K`;
}

/**
 * The value labels: 4 or 5 of them, evenly spaced, from 0 to a round number
 * just above the highest total. Steps are whole numbers (1, 2, 2.5, or 5,
 * times 1, 10, 100...), so a graph with 3 users says 0, 1, 2, 3, 4, never 0.5.
 */
function valueTicks(highest: number): number[] {
  for (let scale = 1; ; scale *= 10) {
    for (const m of [1, 2, 2.5, 5]) {
      const step = m * scale;
      if (!Number.isInteger(step)) continue;
      // Always above the highest total, so the line never touches the top.
      const spans = Math.floor(highest / step) + 1;
      if (spans <= 4) return Array.from({ length: Math.max(spans, 3) + 1 }, (_, i) => i * step);
    }
  }
}

/**
 * Which points get a bottom label: up to 7, always the same step apart, and
 * never so close that 2 labels touch. That gives 5 to 7 on every range, fewer
 * only when there are fewer points. Hours land on round clock hours (every 4
 * hours: 12 AM, 4 AM, 8 AM...). Days count back from today, so today always
 * has a label.
 */
function labelledPoints(points: UsersGraph["points"], step: UsersGraph["step"], width: number): number[] {
  const last = points.length - 1;
  if (last <= 0) return points.length ? [0] : [];
  const widest = Math.max(...points.map((p) => axisText(p.start, step).length)) * CHAR_WIDTH + LABEL_GAP;
  const pick = (stride: number) =>
    points
      .map((_, i) => i)
      .filter((i) => (step === "hour" ? localHour(points[i].start) % stride === 0 : (last - i) % stride === 0));
  for (const stride of STRIDES[step]) {
    const found = pick(stride);
    // How far apart 2 labels a stride apart are, in pixels.
    const apart = (width * stride) / last;
    if (found.length <= 7 && apart >= widest) return found;
  }
  return pick(STRIDES[step][STRIDES[step].length - 1]);
}

// The graph is drawn at its real width, so its text stays 12px on a phone instead of shrinking.
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(260, Math.round(entry.contentRect.width))));
    observer.observe(box);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Graph({ graph }: { graph: UsersGraph }) {
  const { step, points } = graph;
  const [picked, setPicked] = useState<number | null>(null);
  const [ref, W] = useWidth();

  // A new range has different points, so the old pick means nothing.
  useEffect(() => setPicked(null), [graph]);

  // On a phone, tapping anywhere outside the graph hides the card.
  useEffect(() => {
    if (picked === null) return;
    function hide(event: Event) {
      if (!(event.target instanceof Element) || !event.target.closest(".plot-hit")) setPicked(null);
    }
    document.addEventListener("pointerdown", hide);
    return () => document.removeEventListener("pointerdown", hide);
  }, [picked]);

  if (points.length === 0) return <p className="hint">Nobody has signed up yet.</p>;

  const ticks = valueTicks(Math.max(...points.map((p) => p.total)));
  const top = ticks[ticks.length - 1];
  const last = points.length - 1;
  const plotW = W - PAD.left - PAD.right;
  const x = (i: number) => PAD.left + (last === 0 ? plotW / 2 : (i / last) * plotW);
  const y = (v: number) => PAD.top + (1 - v / top) * (H - PAD.top - PAD.bottom);
  // Straight lines between points. A smoothed curve can dip where the total never did.
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.total)}`).join(" ");
  const labelled = labelledPoints(points, step, plotW);
  // Labels are centred under their point. Only one that would run off the graph lines up with its edge instead.
  const anchor = (i: number, text: string) => {
    const half = (text.length * CHAR_WIDTH) / 2;
    return x(i) - half < 0 ? "start" : x(i) + half > W ? "end" : "middle";
  };

  // The point closest to the pointer, along the x axis only, like YouTube's graphs.
  function nearest(event: PointerEvent<SVGRectElement>): number {
    const svg = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    // From screen pixels to the graph's own units, then to how far along the plot it is.
    const along = ((event.clientX - svg.left) * (W / svg.width) - PAD.left) / plotW;
    return Math.min(last, Math.max(0, Math.round(along * last)));
  }

  function onKey(event: KeyboardEvent<SVGSVGElement>) {
    const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity };
    if (!(event.key in moves)) return;
    event.preventDefault();
    setPicked((now) => Math.min(last, Math.max(0, (now ?? last) + moves[event.key])));
  }

  const point = picked === null ? null : points[picked];
  // The card is centred over its point, but near an edge it slides inward so it never runs off the graph.
  const tipShift = picked === null ? 0 : x(picked) < 80 ? 0 : x(picked) > W - 80 ? -100 : -50;
  return (
    <figure className="stats-graph">
      <figcaption className="visually-hidden">
        Total users, one point per {step}. Point at or tap the graph, or use the arrow keys, to see each {step}.
      </figcaption>
      <div className="graph-box" ref={ref}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width={W}
          height={H}
          role="group"
          tabIndex={0}
          aria-label={`Total users from ${pointText(points[0].start, step)} to ${pointText(points[last].start, step)}`}
          onKeyDown={onKey}
          // The keyboard starts on the newest point.
          onFocus={() => setPicked((now) => now ?? last)}
          onBlur={() => setPicked(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? "grid base" : "grid"} />
              <text x={W - PAD.right + 10} y={y(t)} dy="0.35em" className="tick value">{valueText(t)}</text>
            </g>
          ))}
          {labelled.map((i) => {
            const text = axisText(points[i].start, step);
            return (
              <text key={i} x={x(i)} y={H - 8} textAnchor={anchor(i, text)} className="tick date">{text}</text>
            );
          })}
          {picked !== null && <line x1={x(picked)} x2={x(picked)} y1={PAD.top} y2={H - PAD.bottom} className="crosshair" />}
          <path d={line} stroke={LINE} className="series" />
          {/* No dot on every point: only the one being looked at. */}
          {point && picked !== null && (
            <circle cx={x(picked)} cy={y(point.total)} r={5} fill={LINE} className="dot picked" />
          )}
          {/* Catches the mouse or a tap anywhere over the plot, and picks the closest point. */}
          {/* It reaches the right edge too, so pointing at the value labels picks the newest point. */}
          <rect
            x={PAD.left}
            y={0}
            width={W - PAD.left}
            height={H - PAD.bottom}
            className="plot-hit"
            // A mouse shows the card only while it's over the graph.
            onPointerMove={(e) => e.pointerType === "mouse" && setPicked(nearest(e))}
            onPointerLeave={(e) => e.pointerType === "mouse" && setPicked(null)}
            // A finger has no hover, so a tap shows it. Tapping outside the graph hides it (see above).
            onPointerDown={(e) => e.pointerType !== "mouse" && setPicked(nearest(e))}
          />
        </svg>
        {point && picked !== null && (
          <div className="graph-tip" style={{ left: x(picked), transform: `translateX(${tipShift}%)` }} role="status">
            <span className="tip-day">{pointText(point.start, step)}</span>
            <span className="tip-total">
              <strong>{count(point.total)}</strong> {point.total === 1 ? "user" : "users"}
            </span>
          </div>
        )}
      </div>
    </figure>
  );
}

function UsersCard() {
  const [range, setRange] = useState<GraphRange>("7d");
  const [graph, setGraph] = useState<UsersGraph | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    setError("");
    api.userTotals(range).then(
      (answer) => current && setGraph(answer),
      (e) => current && setError(e instanceof ApiError ? e.message : "Couldn't load the graph. Try again."),
    );
    // A slow answer for an old choice never replaces a newer one.
    return () => {
      current = false;
    };
  }, [range]);

  // Every range ends now, so its last point is today's total.
  const total = graph ? (graph.points.at(-1)?.total ?? 0) : null;
  return (
    <section className="card stats-section" aria-labelledby="graph-title">
      <div className="graph-head">
        <h2 id="graph-title">Total users over time</h2>
        <label className="range-picker">
          Show
          <select value={range} onChange={(e) => setRange(e.target.value as GraphRange)}>
            {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
      </div>
      {total !== null && !error && (
        <p className="users-total">PrayerFit has {count(total)} {total === 1 ? "user" : "users"}</p>
      )}
      {error ? (
        <p className="error" role="alert">{error}</p>
      ) : graph ? (
        <Graph graph={graph} />
      ) : (
        <p className="hint">Loading…</p>
      )}
    </section>
  );
}

export function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch((e) => {
      // 404 for anyone but the admin, and 401 when signed out: both look like a page that isn't there.
      if (e instanceof ApiError && (e.status === 404 || e.status === 401)) setNotFound(true);
      else setError(e instanceof ApiError ? e.message : "Couldn't load the stats. Refresh to try again.");
    });
  }, []);

  if (notFound) {
    return (
      <main className="page narrow">
        <h1>Page not found</h1>
        <p><a href="/">Go to the home page</a></p>
      </main>
    );
  }
  if (error) return <main className="page narrow"><p className="error" role="alert">{error}</p></main>;
  if (!stats) return <main className="page narrow"><p className="hint">Loading…</p></main>;

  return (
    <main className="page stats-page">
      <h1>Stats</h1>

      <UsersCard />

      <section className="card stats-section" aria-labelledby="masjids-title">
        <h2 id="masjids-title">Masajid</h2>
        {stats.masjids.length === 0 ? (
          <p>Nobody has picked one yet.</p>
        ) : (
          <table className="masjid-table">
            <thead>
              {/* The card's title already says what the names are, so that column has no visible header. */}
              <tr><th scope="col"><span className="visually-hidden">Name</span></th><th scope="col">Users</th></tr>
            </thead>
            <tbody>
              {stats.masjids.map((m, i) => (
                <tr key={`${m.name}-${i}`}>
                  <td>
                    {m.name}
                    {!m.mawaqit_linked && <span className="tag">No MAWAQIT times</span>}
                  </td>
                  <td>{m.users}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
