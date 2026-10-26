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

const H = 260;
const PAD = { top: 20, right: 24, bottom: 40, left: 44 };
// Closer than this, the dots would run into each other, so only the line is drawn (and the picked dot).
const MIN_DOT_GAP = 16;

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

  // On a phone, tapping anywhere outside the graph hides the box.
  useEffect(() => {
    if (picked === null) return;
    function hide(event: Event) {
      if (!(event.target instanceof Element) || !event.target.closest(".plot-hit")) setPicked(null);
    }
    document.addEventListener("pointerdown", hide);
    return () => document.removeEventListener("pointerdown", hide);
  }, [picked]);

  if (points.length === 0) return <p className="hint">Nobody has signed up yet.</p>;

  const max = Math.max(1, ...points.map((p) => p.total));
  const last = points.length - 1;
  const plotW = W - PAD.left - PAD.right;
  const x = (i: number) => PAD.left + (last === 0 ? plotW / 2 : (i / last) * plotW);
  const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.total)}`).join(" ");
  const ticks = [...new Set([0, Math.round(max / 2), max])];
  const showDots = last === 0 || plotW / last >= MIN_DOT_GAP;
  // The first and last labels need this much room between them, or they run into each other.
  const labelRoom = step === "hour" ? 210 : 96;

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
  // Near an edge, the box opens inward so it never runs off the graph. It sits
  // just below a point in the top half, and just above one in the bottom half,
  // so it never covers the point it's about.
  const tipShift = picked === null ? 0 : x(picked) < 90 ? 0 : x(picked) > W - 90 ? -100 : -50;
  const dotY = point ? y(point.total) : 0;
  const below = dotY < H / 2;
  return (
    <figure className="stats-graph">
      <figcaption>
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
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
              <text x={PAD.left - 10} y={y(t)} dy="0.35em" textAnchor="end" className="tick">{t}</text>
            </g>
          ))}
          {/* Dates go below the axis, well clear of the 0 on the side. */}
          <text x={x(0)} y={H - 10} textAnchor={last === 0 ? "middle" : "start"} className="tick date">
            {pointText(points[0].start, step)}
          </text>
          {last > 0 && x(last) - x(0) >= labelRoom && (
            <text x={x(last)} y={H - 10} textAnchor="end" className="tick date">{pointText(points[last].start, step)}</text>
          )}
          {picked !== null && <line x1={x(picked)} x2={x(picked)} y1={PAD.top} y2={H - PAD.bottom} className="crosshair" />}
          <path d={line} stroke={LINE} className="series" />
          {points.map((p, i) =>
            showDots || picked === i ? (
              <circle
                key={p.start}
                cx={x(i)}
                cy={y(p.total)}
                r={picked === i ? 6 : 4}
                fill={LINE}
                className={picked === i ? "dot picked" : "dot"}
              />
            ) : null,
          )}
          {/* Catches the mouse or a tap anywhere over the plot, and picks the closest point. */}
          <rect
            x={PAD.left - 12}
            y={0}
            width={plotW + 24}
            height={H - PAD.bottom + 8}
            className="plot-hit"
            // A mouse shows the box only while it's over the graph.
            onPointerMove={(e) => e.pointerType === "mouse" && setPicked(nearest(e))}
            onPointerLeave={(e) => e.pointerType === "mouse" && setPicked(null)}
            // A finger has no hover, so a tap shows it. Tapping outside the graph hides it (see above).
            onPointerDown={(e) => e.pointerType !== "mouse" && setPicked(nearest(e))}
          />
        </svg>
        {point && picked !== null && (
          <div
            className="graph-tip"
            style={{
              left: x(picked),
              top: below ? dotY + 14 : dotY - 14,
              transform: `translate(${tipShift}%, ${below ? 0 : -100}%)`,
            }}
            role="status"
          >
            <span className="tip-day">{pointText(point.start, step)}</span>
            <span><strong>{point.total}</strong> {point.total === 1 ? "user" : "users"}</span>
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

  return (
    <section className="card stats-section" aria-labelledby="graph-title">
      <h2 id="graph-title">Total users over time</h2>
      <label className="range-picker">
        Show
        <select value={range} onChange={(e) => setRange(e.target.value as GraphRange)}>
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      </label>
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
