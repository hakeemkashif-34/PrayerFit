// Loads the masjids near the saved address, for the masjid and Jumuah steps.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Nearby } from "../types";

export function useNearby() {
  const [nearby, setNearby] = useState<Nearby | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setNearby(await api.nearbyMasjids());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load nearby masjids. Try again.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { nearby, error, retry: load };
}
