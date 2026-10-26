// The private /stats page: total users, a graph of total users over time,
// and how many users picked each masjid. Only the ADMIN_EMAIL account can
// open it. The API answers 404 for everyone else, so this page just says
// "Page not found", the same as any page that doesn't exist. Nothing links here.
//
// Counts only. No emails, names, or addresses are ever sent.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Stats } from "./types";

// Checked with the dataviz palette validator on white.
const LINE = "#1f8a52";

const H = 260;
const PAD = { top: 20, right: 24, bottom: 40, left: 44 };
// Under this many pixels apart, the first and last date labels would run into each other.
const LABEL_ROOM = 96;

function dayText(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-CA", { month: "short", day: "numeric", timeZone: "UTC" });
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

function Graph({ history }: { history: Stats["history"] }) {
  const [picked, setPicked] = useState<number | null>(null);
  const [ref, W] = useWidth();

  // On a phone, tapping anywhere that isn't a dot hides the box.
  useEffect(() => {
    if (picked === null) return;
    function hide(event: Event) {
      if (!(event.target instanceof Element) || !event.target.closest(".dot-target")) setPicked(null);
    }
    document.addEventListener("pointerdown", hide);
    return () => document.removeEventListener("pointerdown", hide);
  }, [picked]);
  if (history.length === 0) return <p className="hint">Nobody has signed up yet.</p>;

  const max = Math.max(1, ...history.map((d) => d.total));
  const last = history.length - 1;
  const x = (i: number) => PAD.left + (last === 0 ? 0 : (i / last) * (W - PAD.left - PAD.right));
  const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom);
  const line = history.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.total)}`).join(" ");
  const ticks = [...new Set([0, Math.round(max / 2), max])];

  const point = picked === null ? null : history[picked];
  // Near an edge, the box opens inward so it never runs off the graph. It sits
  // just below a dot in the top half, and just above one in the bottom half,
  // so it never covers the dot it's about.
  const tipShift = picked === null ? 0 : x(picked) < 90 ? 0 : x(picked) > W - 90 ? -100 : -50;
  const dotY = point ? y(point.total) : 0;
  const below = dotY < H / 2;
  return (
    <figure className="stats-graph">
      <figcaption>Total users, one dot per day. Point at or tap a dot for that day.</figcaption>
      <div className="graph-box" ref={ref}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width={W}
          height={H}
          role="group"
          aria-label={`Total users over time, from ${dayText(history[0].day)} to ${dayText(history[last].day)}`}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
              <text x={PAD.left - 10} y={y(t)} dy="0.35em" textAnchor="end" className="tick">{t}</text>
            </g>
          ))}
          {/* Dates go below the axis, well clear of the 0 on the side. */}
          <text x={x(0)} y={H - 10} textAnchor={last === 0 ? "middle" : "start"} className="tick date">{dayText(history[0].day)}</text>
          {last > 0 && x(last) - x(0) >= LABEL_ROOM && (
            <text x={x(last)} y={H - 10} textAnchor="end" className="tick date">{dayText(history[last].day)}</text>
          )}
          {picked !== null && <line x1={x(picked)} x2={x(picked)} y1={PAD.top} y2={H - PAD.bottom} className="crosshair" />}
          <path d={line} stroke={LINE} className="series" />
          {history.map((d, i) => (
            <g
              key={d.day}
              className="dot-target"
              // A mouse shows the box only while it's over the dot, like YouTube.
              onPointerEnter={(e) => e.pointerType === "mouse" && setPicked(i)}
              onPointerLeave={(e) => e.pointerType === "mouse" && setPicked((now) => (now === i ? null : now))}
              // A finger has no hover, so a tap shows it. Tapping anywhere else hides it (see below).
              onPointerDown={(e) => e.pointerType !== "mouse" && setPicked(i)}
            >
              {/* A bigger, invisible circle around each dot, so it's easy to point at or tap. */}
              <circle cx={x(i)} cy={y(d.total)} r={12} className="dot-hit" />
              <circle
                cx={x(i)}
                cy={y(d.total)}
                r={picked === i ? 6 : 4}
                fill={LINE}
                className={picked === i ? "dot picked" : "dot"}
                tabIndex={0}
                aria-label={`${dayText(d.day)}: ${d.signed_up} signed up, ${d.total} in total`}
                onFocus={() => setPicked(i)}
                onBlur={() => setPicked(null)}
              />
            </g>
          ))}
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
            <span className="tip-day">{dayText(point.day)}</span>
            <span><strong>{point.signed_up}</strong> signed up that day</span>
            <span><strong>{point.total}</strong> in total</span>
          </div>
        )}
      </div>
    </figure>
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
      <p className="total-users">Total users: <strong>{stats.total_users}</strong></p>

      <section className="card stats-section" aria-labelledby="graph-title">
        <h2 id="graph-title">Total users over time</h2>
        <Graph history={stats.history} />
      </section>

      <section className="card stats-section" aria-labelledby="masjids-title">
        <h2 id="masjids-title">Masjids</h2>
        {stats.masjids.length === 0 ? (
          <p>Nobody has picked a masjid yet.</p>
        ) : (
          <table className="masjid-table">
            <thead>
              <tr><th scope="col">Masjid</th><th scope="col">Users</th></tr>
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
