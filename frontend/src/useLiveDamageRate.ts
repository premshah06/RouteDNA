import { useEffect, useRef, useState } from "react";
import type { PackagePosition } from "./useLiveFeed";

// How far back a scan still counts toward the live damage rate — a
// rolling window, not a cumulative "since page load" count, so the
// number reflects what's happening right now rather than drifting
// toward whatever the very first few minutes looked like.
const WINDOW_MS = 10 * 60 * 1000;
const SWEEP_MS = 15 * 1000;

interface Observation {
  atMs: number;
  damaged: boolean;
}

/** Derives a real-time damage rate from the live position stream —
 * `PositionUpdate.damage_detected` is the only live damage signal that
 * exists (no streaming job emits a damage Alert; see
 * live_feed_service.proto's comment on that field), so this hook
 * watches for scans (a position's updatedAtMs advancing) and keeps a
 * rolling count of damaged vs. total, independent of the batch-sourced
 * damageRate in useFacilityStats which can be a full day stale. */
export function useLiveDamageRate(positions: Map<string, PackagePosition>) {
  const [observations, setObservations] = useState<Observation[]>([]);
  const lastSeenRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const fresh: Observation[] = [];
    for (const position of positions.values()) {
      const lastSeen = lastSeenRef.current.get(position.packageId);
      if (lastSeen !== position.updatedAtMs) {
        fresh.push({ atMs: position.updatedAtMs, damaged: position.damageDetected });
        lastSeenRef.current.set(position.packageId, position.updatedAtMs);
      }
    }
    if (fresh.length > 0) {
      setObservations((prev) => [...prev, ...fresh]);
    }
  }, [positions]);

  useEffect(() => {
    const interval = setInterval(() => {
      const cutoff = Date.now() - WINDOW_MS;
      setObservations((prev) => {
        const next = prev.filter((o) => o.atMs >= cutoff);
        return next.length === prev.length ? prev : next;
      });
    }, SWEEP_MS);
    return () => clearInterval(interval);
  }, []);

  const cutoff = Date.now() - WINDOW_MS;
  const windowed = observations.filter((o) => o.atMs >= cutoff);
  const damaged = windowed.filter((o) => o.damaged).length;

  return {
    damageRate: windowed.length > 0 ? damaged / windowed.length : 0,
    sampleSize: windowed.length,
  };
}
