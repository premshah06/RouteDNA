import { useEffect, useMemo, useRef, useState } from "react";
import type { AlertItem, PackagePosition } from "./useLiveFeed";
import { STATIONS, type StationType } from "./constants";
import type { StationVisualState } from "./StationIcon";

// How far back an alert still counts toward a station's visual state —
// a stuck-package alert from an hour ago shouldn't keep a station
// glowing red forever once the facility has moved on.
const STATION_ALERT_WINDOW_MS = 5 * 60 * 1000;

// A dot rides its belt path for this long before landing in the
// destination station — long enough to read as motion, short enough
// that a burst of scans doesn't leave the canvas cluttered with
// travelers.
export const TRAVEL_MS = 1400;
// After landing, a package stays highlighted this long so a glance at
// its station still shows "something just arrived here."
export const RECENTLY_ARRIVED_MS = 4000;

// Mirrors stream_processing/jobs/stuck_package_detector.py's
// STUCK_THRESHOLD_MS — no live config endpoint exposes this value
// ahead of an alert actually firing, so it's duplicated here (same
// convention as TRAVEL_MS above) to flag packages trending toward a
// STUCK alert before the backend detector itself fires one.
const STUCK_THRESHOLD_MS = 10 * 60 * 1000;
const AT_RISK_FRACTION = 0.8;
// An independent, softer threshold — "running behind" is a distinct
// signal from "about to trip a STUCK alert," not just an earlier point
// on the same scale, so this isn't derived from STUCK_THRESHOLD_MS.
const DELAYED_THRESHOLD_MS = 5 * 60 * 1000;

export interface Traveler {
  packageId: string;
  from: StationType;
  to: StationType;
  startedAtMs: number;
  itemCategory: number;
}

// Facility's real linear routing chain (see services/ingestion/server.py's
// _NEXT_STATION and journey_correlator.py's EXPECTED_PATH) — every
// package moves exactly one step forward through STATIONS at a time,
// so "the belt this traveler rides" is just "the segment between two
// adjacent stations in that fixed order," not a lookup table of
// specific from/to pairs.
function isAdjacentStep(from: StationType, to: StationType): boolean {
  const fromIdx = STATIONS.findIndex((s) => s.type === from);
  const toIdx = STATIONS.findIndex((s) => s.type === to);
  return fromIdx !== -1 && toIdx === fromIdx + 1;
}

/** Shared tracking state for the Live view: which packages are mid-
 * transit (animating between two adjacent stations), which just
 * arrived (still worth highlighting), and each station's alert-derived
 * visual state. Used by both FloorPlan and the lane list so they read
 * from one consistent source instead of duplicating the diffing logic. */
export function useFloorPlanTracking(positions: Map<string, PackagePosition>, alerts: AlertItem[]) {
  const [travelers, setTravelers] = useState<Map<string, Traveler>>(new Map());
  const [arrivals, setArrivals] = useState<Map<string, number>>(new Map());
  const lastStationRef = useRef<Map<string, StationType>>(new Map());

  // Diffs incoming positions against last-seen stations to detect real
  // station *changes* (PositionUpdate fires on every scan, not just on
  // movement) and starts a travel animation for each one. Runs as an
  // effect, not inline in render, so it's a one-shot reaction to
  // `positions` changing rather than re-running on every animation tick.
  useEffect(() => {
    const newTravelers = new Map<string, Traveler>();
    const newArrivals = new Map<string, number>();
    const startedAt = Date.now();

    for (const position of positions.values()) {
      const prevStation = lastStationRef.current.get(position.packageId);
      if (prevStation !== undefined && prevStation !== position.station) {
        if (isAdjacentStep(prevStation, position.station)) {
          newTravelers.set(position.packageId, {
            packageId: position.packageId,
            from: prevStation,
            to: position.station,
            startedAtMs: startedAt,
            itemCategory: position.itemCategory,
          });
        }
        newArrivals.set(position.packageId, startedAt + TRAVEL_MS);
      }
      lastStationRef.current.set(position.packageId, position.station);
    }

    if (newTravelers.size > 0) {
      setTravelers((prev) => {
        const next = new Map(prev);
        for (const [id, t] of newTravelers) next.set(id, t);
        return next;
      });
    }
    if (newArrivals.size > 0) {
      setArrivals((prev) => {
        const next = new Map(prev);
        for (const [id, at] of newArrivals) next.set(id, at);
        return next;
      });
    }

    // Packages evicted from the live feed (stale/dispatched) shouldn't
    // linger as phantom travelers or arrivals forever.
    setTravelers((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const id of next.keys()) {
        if (!positions.has(id)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    setArrivals((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const id of next.keys()) {
        if (!positions.has(id)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [positions]);

  // Ticks a few times a second purely to advance travel-animation
  // progress and expire "recently arrived" highlights — those are
  // time-relative derived values, not state that changes on its own.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 150);
    return () => clearInterval(interval);
  }, []);

  const activeTravelers = useMemo(
    () => Array.from(travelers.values()).filter((t) => now - t.startedAtMs < TRAVEL_MS),
    [travelers, now]
  );

  // Once a travel animation finishes, drop it — done here (not in the
  // ticking effect) so it's a plain state update reacting to `now`
  // crossing the threshold, not a second independent timer to keep in sync.
  useEffect(() => {
    const finished = Array.from(travelers.values()).filter((t) => now - t.startedAtMs >= TRAVEL_MS);
    if (finished.length === 0) return;
    setTravelers((prev) => {
      const next = new Map(prev);
      for (const t of finished) next.delete(t.packageId);
      return next;
    });
  }, [travelers, now]);

  const stationState = useMemo(() => {
    const state = new Map<StationType, StationVisualState>();
    for (const alert of alerts) {
      if (now - alert.detectedAtMs > STATION_ALERT_WINDOW_MS) continue;
      const severityLabel = alert.severity === 3 ? "critical" : alert.severity === 2 ? "warning" : null;
      if (!severityLabel) continue;
      const current = state.get(alert.station);
      // critical always wins over warning for the same station.
      if (current === "critical") continue;
      state.set(alert.station, severityLabel);
    }
    return state;
  }, [alerts, now]);

  const packagesByStation = useMemo(() => {
    const grouped = new Map<StationType, PackagePosition[]>();
    for (const station of STATIONS) grouped.set(station.type, []);
    for (const position of positions.values()) {
      // Hide a package from its destination station while it's still
      // animating there — it "arrives" visually when the travel
      // animation finishes, not the instant the scan is received.
      const traveler = travelers.get(position.packageId);
      if (traveler && now - traveler.startedAtMs < TRAVEL_MS) continue;
      const list = grouped.get(position.station);
      if (list) list.push(position);
    }
    return grouped;
  }, [positions, travelers, now]);

  const { delayedCount, atRiskCount } = useMemo(() => {
    let delayed = 0;
    let atRisk = 0;
    for (const position of positions.values()) {
      const dwell = now - position.updatedAtMs;
      if (dwell >= STUCK_THRESHOLD_MS * AT_RISK_FRACTION && dwell < STUCK_THRESHOLD_MS) atRisk++;
      if (dwell >= DELAYED_THRESHOLD_MS) delayed++;
    }
    return { delayedCount: delayed, atRiskCount: atRisk };
  }, [positions, now]);

  return { now, activeTravelers, arrivals, stationState, packagesByStation, delayedCount, atRiskCount };
}
