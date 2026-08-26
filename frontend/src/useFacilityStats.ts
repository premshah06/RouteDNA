import { useEffect, useState } from "react";
import { QueryServiceClient } from "@thing-transfer/proto-gen/packagepb/v1/Query_serviceServiceClientPb";
import * as queryPb from "@thing-transfer/proto-gen/packagepb/v1/query_service_pb";
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";

const { GetFacilityStatsRequest } = queryPb;

export type TrendsRangePreset = "today" | "week" | "month";
export interface CustomDateRange {
  start: string; // "YYYY-MM-DD"
  end: string; // "YYYY-MM-DD"
}
// Either a preset or an explicit start/end — see
// GetFacilityStatsRequest in query_service.proto for how the server
// resolves this (custom wins when both start/end are set).
export type TrendsRange = TrendsRangePreset | CustomDateRange;

function isCustomRange(range: TrendsRange): range is CustomDateRange {
  return typeof range === "object";
}

export interface ThroughputPoint {
  bucketMs: number;
  count: number;
}

export interface StationDamageRate {
  station: commonPb.StationType;
  damageRate: number;
}

export interface CategoryDamageRate {
  itemCategory: number;
  damageRate: number;
}

export interface AlertTypeCount {
  alertType: alertPb.AlertType;
  count: number;
}

export interface HourlyCount {
  hour: number;
  count: number;
}

export interface AlertTrendPoint {
  bucketMs: number;
  alertType: alertPb.AlertType;
  count: number;
}

export interface FlaggedParcel {
  packageId: string;
  alertType: alertPb.AlertType;
  station: commonPb.StationType;
  detectedAtMs: number;
}

export interface FacilityStats {
  throughputTotal: number;
  damageRate: number;
  throughputSeries: ThroughputPoint[];
  damageByStation: StationDamageRate[];
  damageByCategory: CategoryDamageRate[];
  alertBreakdown: AlertTypeCount[];
  busiestHours: HourlyCount[];
  alertTrend: AlertTrendPoint[];
  recentFlagged: FlaggedParcel[];
}

const QUERY_URL = import.meta.env.VITE_QUERY_URL ?? "http://localhost:8090";
// Trends tab is a dashboard someone leaves open, not a one-shot report
// — refetch periodically so it stays current without a manual reload.
const REFETCH_MS = 30_000;

function toMs(ts: { getSeconds(): number; getNanos(): number } | undefined): number {
  return ts ? ts.getSeconds() * 1000 + ts.getNanos() / 1e6 : Date.now();
}

/** Fetches facility-wide stats for the Trends tab, refetching on an
 * interval and whenever `range` changes. Only call this while the
 * Trends tab is actually visible — pass a stable `range` and mount/
 * unmount the component to control when polling runs. `range` is
 * either a preset ("today"/"week"/"month") or an explicit
 * {start, end} custom range. */
export function useFacilityStats(range: TrendsRange) {
  const [stats, setStats] = useState<FacilityStats | null>(null);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");

  // Custom ranges are objects, so a new one is a new reference on every
  // render even with the same dates — key the effect on the actual
  // values instead of the object identity so this doesn't refetch on
  // every unrelated re-render of the caller.
  const rangeKey = isCustomRange(range) ? `${range.start}:${range.end}` : range;

  useEffect(() => {
    let cancelled = false;

    function fetchStats() {
      setStatus("loading");
      const client = new QueryServiceClient(QUERY_URL);
      const request = new GetFacilityStatsRequest();
      if (isCustomRange(range)) {
        request.setStartDate(range.start);
        request.setEndDate(range.end);
      } else {
        request.setRange(range);
      }

      client
        .getFacilityStats(request, {})
        .then((response) => {
          if (cancelled) return;
          setStats({
            throughputTotal: response.getThroughputTotal(),
            damageRate: response.getDamageRate(),
            throughputSeries: response.getThroughputSeriesList().map((p) => ({
              bucketMs: toMs(p.getBucket()),
              count: p.getCount(),
            })),
            damageByStation: response.getDamageByStationList().map((d) => ({
              station: d.getStation(),
              damageRate: d.getDamageRate(),
            })),
            damageByCategory: response.getDamageByCategoryList().map((d) => ({
              itemCategory: d.getItemCategory(),
              damageRate: d.getDamageRate(),
            })),
            alertBreakdown: response.getAlertBreakdownList().map((a) => ({
              alertType: a.getAlertType(),
              count: a.getCount(),
            })),
            busiestHours: response.getBusiestHoursList().map((h) => ({
              hour: h.getHour(),
              count: h.getCount(),
            })),
            alertTrend: response.getAlertTrendList().map((t) => ({
              bucketMs: toMs(t.getBucket()),
              alertType: t.getAlertType(),
              count: t.getCount(),
            })),
            recentFlagged: response.getRecentFlaggedList().map((f) => ({
              packageId: f.getPackageId(),
              alertType: f.getAlertType(),
              station: f.getStation(),
              detectedAtMs: toMs(f.getDetectedAt()),
            })),
          });
          setStatus("loaded");
        })
        .catch(() => {
          if (!cancelled) setStatus("error");
        });
    }

    fetchStats();
    const interval = setInterval(fetchStats, REFETCH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rangeKey]);

  return { stats, status };
}
