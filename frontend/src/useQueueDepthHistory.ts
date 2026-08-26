import { useEffect, useRef, useState } from "react";
import { STATIONS, type StationType } from "./constants";
import type { PackagePosition } from "./useLiveFeed";

const WINDOW_MS = 30 * 60 * 1000;
const SAMPLE_INTERVAL_MS = 20_000;

export interface QueueDepthSample {
  atMs: number;
  counts: Record<StationType, number>;
}

/** Samples current per-station occupancy on a coarse interval into a
 * client-side, in-memory 30-minute rolling window — purely additive to
 * whatever positions/packagesByStation already track, no backend query.
 * Resets on unmount/reload, same tradeoff as any other client-only
 * history in this app. */
export function useQueueDepthHistory(packagesByStation: Map<StationType, PackagePosition[]>) {
  const [samples, setSamples] = useState<QueueDepthSample[]>([]);
  // Read inside the interval without re-subscribing the interval itself
  // on every packagesByStation identity change (it's a new Map each
  // render) — the interval only needs the latest snapshot at tick time.
  const latestRef = useRef(packagesByStation);
  latestRef.current = packagesByStation;

  useEffect(() => {
    function sample() {
      const counts = {} as Record<StationType, number>;
      for (const station of STATIONS) counts[station.type] = latestRef.current.get(station.type)?.length ?? 0;
      const atMs = Date.now();
      setSamples((prev) => {
        const cutoff = atMs - WINDOW_MS;
        const next = prev.filter((s) => s.atMs >= cutoff);
        next.push({ atMs, counts });
        return next;
      });
    }
    sample();
    const interval = setInterval(sample, SAMPLE_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  return samples;
}
