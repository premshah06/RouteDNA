import { useEffect, useState } from "react";
import { QueryServiceClient } from "@thing-transfer/proto-gen/packagepb/v1/Query_serviceServiceClientPb";
// Namespace import — see useLiveFeed.ts for why (protoc-gen-js CJS/
// dynamic-export interop).
import * as queryPb from "@thing-transfer/proto-gen/packagepb/v1/query_service_pb";
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";

const { GetStationStatsRequest } = queryPb;
export type StationType = commonPb.StationType;

export interface StationThroughputPoint {
  bucketMs: number;
  count: number;
}

export interface StationAlertTypeCount {
  alertType: alertPb.AlertType;
  count: number;
}

export interface StationStats {
  station: StationType;
  throughputSeries: StationThroughputPoint[];
  damageRate: number;
  alertBreakdown: StationAlertTypeCount[];
}

const QUERY_URL = import.meta.env.VITE_QUERY_URL ?? "http://localhost:8090";

function toMs(ts: { getSeconds(): number; getNanos(): number } | undefined): number {
  return ts ? ts.getSeconds() * 1000 + ts.getNanos() / 1e6 : Date.now();
}

/** Fetches historical throughput/damage/alert aggregates for one
 * station on demand — used by the Checkpoint Operations panel when a
 * station is clicked. `station` of null means "panel closed," and the
 * hook does nothing. Fetch-once-per-open, same as usePackageJourney —
 * live occupancy/alert-state for the station comes from
 * useFloorPlanTracking instead, this hook only covers what needs a
 * warehouse read. */
export function useStationStats(station: StationType | null) {
  const [stats, setStats] = useState<StationStats | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "loaded" | "error">("idle");

  useEffect(() => {
    if (station === null) {
      setStats(null);
      setStatus("idle");
      return;
    }

    let cancelled = false;

    function fetchStats() {
      setStatus("loading");
      setStats(null);

      const client = new QueryServiceClient(QUERY_URL);
      const request = new GetStationStatsRequest();
      request.setStation(station!);
      request.setRange("today");

      client
        .getStationStats(request, {})
        .then((response) => {
          if (cancelled) return;
          setStats({
            station: response.getStation(),
            throughputSeries: response.getThroughputSeriesList().map((p) => ({
              bucketMs: toMs(p.getBucket()),
              count: p.getCount(),
            })),
            damageRate: response.getDamageRate(),
            alertBreakdown: response.getAlertBreakdownList().map((a) => ({
              alertType: a.getAlertType(),
              count: a.getCount(),
            })),
          });
          setStatus("loaded");
        })
        .catch(() => {
          if (!cancelled) setStatus("error");
        });
    }

    fetchStats();

    return () => {
      cancelled = true;
    };
  }, [station]);

  return { stats, status };
}
