// Setup page 1, "Required": location, main masjid (or "I pray at home"),
// the weekly grid, and which Jumuah, all on one page and all shown at once.
//
// Picking a location saves it straight away, since the masjid search needs
// it to sort masjids by distance. Next saves the masjid, the grid, and the
// Jumuah pick. The Jumuah question shows as soon as a masjid is picked. If
// that masjid has no Jumuah times yet, it says so, and the 1st Jumuah is saved.
// Someone who prays at home has no Jumuah masjid, so there's no question.
// Nothing goes to Google Calendar until the user presses Finish or Skip on
// page 2.

import { useState } from "react";
import { api, ApiError } from "../api";
import { JumuahChooser } from "../JumuahChooser";
import { distanceText, masjidName } from "../labels";
import type { Masjid, Prayer, Settings, SlotKey } from "../types";
import { LocationStep } from "./LocationStep";
import { MasjidSearch } from "./MasjidSearch";
import { emptyWeek, WeeklyGrid } from "./WeeklyStep";

type Props = {
  settings: Settings;
  // The location saved. The page stays.
  onChange: (settings: Settings) => void;
  // Everything on the page is saved. Go to page 2.
  onNext: (settings: Settings) => void;
};

export function RequiredPage({ settings, onChange, onNext }: Props) {
  const [choice, setChoice] = useState<"masjid" | "home" | null>(settings.main_masjid_choice);
  const [picked, setPicked] = useState<Masjid | null>(settings.main_masjid);
  const [days, setDays] = useState(settings.weekly.length === 7 ? settings.weekly : emptyWeek());
  const [pick, setPick] = useState<SlotKey | null>(settings.jumuah_pick);
  // How many Jumuah slots the question shows. 0 means it was skipped.
  const [slotCount, setSlotCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const hasLocation = settings.place_name !== null;
  const atMasjid = choice === "masjid" && picked !== null;


  function toggle(weekday: number, prayer: Prayer) {
    setDays((current) => current.map((d) => (d.weekday === weekday ? { ...d, [prayer]: !d[prayer] } : d)));
  }

  function pickMasjid(masjid: Masjid) {
    setPicked(masjid);
    setChoice("masjid");
  }

  async function next() {
    if (!hasLocation) return setError("Pick your location from the list.");
    if (choice === null || (choice === "masjid" && !picked)) {
      return setError("Pick your masjid, or choose I pray at home.");
    }
    setBusy(true);
    setError("");
    try {
      let saved = await api.saveMainMasjid(
        choice === "masjid" && picked ? { choice: "masjid", masjid_id: picked.id } : { choice: "home" },
      );
      if (atMasjid) saved = await api.saveWeekly(days);
      // Jumuah is always at the main masjid: the pick from the question, or its
      // 1st Jumuah when it has no Jumuah times yet. Praying at home means no Jumuah.
      if (atMasjid && picked) {
        const chosen = slotCount > 0 && pick?.masjid_id === picked.id ? pick : { masjid_id: picked.id, order: 1 };
        saved = await api.saveJumuahPick(chosen);
      }
      onNext(saved.settings);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="required-page">
      <h1>Required</h1>

      <LocationStep current={settings.place_name} onSaved={(response) => onChange(response.settings)}
        example="e.g. 24 Maple Drive, Ottawa" />

      <section aria-labelledby="masjid-title" className="page-section">
        <h2 id="masjid-title">Which masjid do you usually go to?</h2>
        <p className="hint example">e.g. Kanata Muslim Association</p>
        {choice === "home" ? (
          <div className="current picked-masjid">
            <p>
              <strong>I pray at home</strong>
            </p>
            <button type="button" className="link" onClick={() => setChoice(picked ? "masjid" : null)} disabled={busy}>
              Change
            </button>
          </div>
        ) : picked && choice === "masjid" ? (
          <div className="current picked-masjid">
            <p>
              <strong>{masjidName(picked)}</strong>
              {picked.distance_km !== null && <span className="hint detail">{distanceText(picked.distance_km)}</span>}
            </p>
            <button type="button" className="link" onClick={() => setChoice(null)} disabled={busy}>
              Change
            </button>
          </div>
        ) : (
          <>
            {/* The search sorts masjids by distance from home, so it waits for the location. */}
            <MasjidSearch onPicked={pickMasjid} disabled={!hasLocation} />
            {!hasLocation && <p className="hint small-line">Pick your location first, so masjids near you come up first.</p>}
            <button type="button" className="link home-choice" onClick={() => setChoice("home")} disabled={busy}>
              I pray at home
            </button>
          </>
        )}
      </section>

      {/* Hidden only for "I pray at home", which already answers it. */}
      {choice !== "home" && (
        <section aria-labelledby="weekly-title" className="page-section">
          <h2 id="weekly-title">Which prayers do you usually pray at {(choice === "masjid" && picked?.name) || "your masjid"}?</h2>
          <p className="hint">Ticked means at the masjid. Unticked means at home.</p>
          <WeeklyGrid days={days} onToggle={toggle} />
        </section>
      )}

      {atMasjid && picked && (
        <div className="page-section">
          <JumuahChooser masjidId={picked.id} selected={pick} onSelect={setPick} onLoaded={setSlotCount} />
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" onClick={() => void next()} disabled={busy}>
          {busy ? "Saving…" : "Next"}
        </button>
      </div>
    </div>
  );
}
