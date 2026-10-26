// The private /stats page: the app's usage counts and a graph of sign-ups and
// active users over time. Only the ADMIN_EMAIL account can open it. The API
// answers 404 for everyone else, so this page just says "Page not found",
// the same as any page that doesn't exist. Nothing links here.
//
// Counts only. No emails, names, or anything about a user is ever sent.

import { useEffect, useState, type PointerEvent } from "react";
import { api, ApiError } from "./api";
import type { Stats } from "./types";

// Checked with the dataviz palette validator: both pass the colour-blindness checks on white.
const SIGNED_UP = "#1f8a52";
const ACTIVE = "#6b4fbb";

const W = 640;
const H = 260;
const PAD = { top: 16, right: 92, bottom: 32, left: 40 };

function dayText(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-CA", { month: "short", day: "numeric", timeZone: "UTC" });
}

function Graph({ history }: { history: Stats["history"] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (history.length === 0) return <p className="hint">The first day's numbers are saved after 4:00 am.</p>;

  const max = Math.max(1, ...history.map((d) => Math.max(d.signed_up, d.active)));
  const x = (i: number) => PAD.left + (history.length === 1 ? 0 : (i / (history.length - 1)) * (W - PAD.left - PAD.right));
  const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom);
  const line = (key: "signed_up" | "active") => history.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d[key])}`).join(" ");
  const ticks = [0, Math.round(max / 2), max];
  const last = history.length - 1;

  // The crosshair snaps to the nearest day.
  function move(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    let nearest = 0;
    history.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(nearest) - px)) nearest = i;
    });
    setHover(nearest);
  }

  const point = hover === null ? null : history[hover];
  return (
    <figure className="stats-graph">
      <figcaption>Sign-ups and active users, one point a day</figcaption>
      <ul className="legend" aria-hidden="true">
        <li><span className="key" style={{ background: SIGNED_UP }} />Signed up</li>
        <li><span className="key" style={{ background: ACTIVE }} />Active</li>
      </ul>
      <div className="graph-box">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Sign-ups and active users over time. The table below has every value."
          onPointerMove={move} onPointerLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
              <text x={PAD.left - 8} y={y(t)} dy="0.35em" textAnchor="end" className="tick">{t}</text>
            </g>
          ))}
          <text x={x(0)} y={H - 8} className="tick">{dayText(history[0].day)}</text>
          {last > 0 && <text x={x(last)} y={H - 8} textAnchor="end" className="tick">{dayText(history[last].day)}</text>}
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="crosshair" />}
          <path d={line("signed_up")} stroke={SIGNED_UP} className="series" />
          <path d={line("active")} stroke={ACTIVE} className="series" />
          {/* Labels at the end of each line, so colour is never the only way to tell them apart. */}
          <text x={x(last) + 8} y={y(history[last].signed_up)} dy="0.35em" className="end-label">Signed up</text>
          <text x={x(last) + 8} y={y(history[last].active)} dy={history[last].active === history[last].signed_up ? "1.4em" : "0.35em"}
            className="end-label">Active</text>
          {point && hover !== null && (
            <>
              <circle cx={x(hover)} cy={y(point.signed_up)} r={4.5} fill={SIGNED_UP} className="dot" />
              <circle cx={x(hover)} cy={y(point.active)} r={4.5} fill={ACTIVE} className="dot" />
            </>
          )}
        </svg>
        {point && hover !== null && (
          <div className="graph-tip" style={{ left: `${(x(hover) / W) * 100}%` }} role="status">
            <span className="tip-day">{dayText(point.day)}</span>
            <span><span className="tip-key" style={{ background: SIGNED_UP }} /><strong>{point.signed_up}</strong> signed up</span>
            <span><span className="tip-key" style={{ background: ACTIVE }} /><strong>{point.active}</strong> active</span>
          </div>
        )}
      </div>
      <details className="graph-table">
        <summary>Show as a table</summary>
        <table>
          <thead>
            <tr><th scope="col">Day</th><th scope="col">Signed up</th><th scope="col">Active</th></tr>
          </thead>
          <tbody>
            {history.map((d) => (
              <tr key={d.day}><td>{dayText(d.day)}</td><td>{d.signed_up}</td><td>{d.active}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
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

  const tiles: [string, number][] = [
    ["Signed up", stats.signed_up],
    ["Finished setup", stats.finished_setup],
    ["Active", stats.active],
    ["New this week", stats.new_this_week],
  ];
  return (
    <main className="page stats-page">
      <h1>Stats</h1>
      <p className="hint">Counts only. Active means the calendar was updated in the last 2 days.</p>
      <div className="stat-tiles">
        {tiles.map(([name, value]) => (
          <div key={name} className="stat-tile">
            <span className="stat-value">{value}</span>
            <span className="stat-name">{name}</span>
          </div>
        ))}
      </div>

      <section className="card stats-section" aria-labelledby="graph-title">
        <h2 id="graph-title">Over time</h2>
        <Graph history={stats.history} />
      </section>

      <section className="card stats-section" aria-labelledby="masjid-times-title">
        <h2 id="masjid-times-title">Masjid times</h2>
        {stats.masjid_times.length === 0 ? (
          <p>Every linked masjid was read in the last 24 hours.</p>
        ) : (
          <ul className="plain masjid-problems">
            {stats.masjid_times.map((m) => (
              <li key={m.name}>
                <strong>{m.name}</strong>
                <span className="hint detail">
                  Last good read: {m.last_success_at ? new Date(m.last_success_at).toLocaleString("en-CA") : "never"}
                </span>
                <span className="hint detail">Error: {m.error ?? "none, but the last good read is over 24 hours old"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
