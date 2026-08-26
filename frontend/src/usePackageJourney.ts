import { useEffect, useState } from "react";
import { QueryServiceClient } from "@thing-transfer/proto-gen/packagepb/v1/Query_serviceServiceClientPb";
// Namespace import — see useLiveFeed.ts for why (protoc-gen-js CJS/
// dynamic-export interop).
import * as queryPb from "@thing-transfer/proto-gen/packagepb/v1/query_service_pb";
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";
import type { StuckDetail, MisroutingDetail, DamageDetail } from "./useLiveFeed";

const { GetPackageJourneyRequest } = queryPb;

export interface JourneyScan {
  eventId: string;
  station: commonPb.StationType;
  scannerId: string;
  scannedAtMs: number;
  result: string;
  damageType: string;
  damageConfidence: number;
}

export interface JourneyAlert {
  alertId: string;
  alertType: alertPb.AlertType;
  severity: alertPb.Severity;
  station: commonPb.StationType;
  message: string;
  detectedAtMs: number;
  stuckDetail?: StuckDetail;
  misroutingDetail?: MisroutingDetail;
  damageDetail?: DamageDetail;
}

export interface PackageJourney {
  packageId: string;
  scans: JourneyScan[];
  alerts: JourneyAlert[];
}

const QUERY_URL = import.meta.env.VITE_QUERY_URL ?? "http://localhost:8090";

function toMs(ts: { getSeconds(): number; getNanos(): number } | undefined): number {
  return ts ? ts.getSeconds() * 1000 + ts.getNanos() / 1e6 : Date.now();
}

/** Fetches scan/alert history for one package on demand — used by the
 * journey side panel when a parcel or alert is clicked. `packageId`
 * of null/empty means "panel closed," and the hook does nothing. */
export function usePackageJourney(packageId: string | null) {
  const [journey, setJourney] = useState<PackageJourney | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "loaded" | "error">("idle");

  useEffect(() => {
    if (!packageId) {
      setJourney(null);
      setStatus("idle");
      return;
    }

    let cancelled = false;

    function fetchJourney() {
      setStatus("loading");
      setJourney(null);

      const client = new QueryServiceClient(QUERY_URL);
      const request = new GetPackageJourneyRequest();
      request.setPackageId(packageId!);

      client
        .getPackageJourney(request, {})
        .then((response) => {
          if (cancelled) return;
          setJourney({
            packageId: response.getPackageId(),
            scans: response.getScansList().map((s) => ({
              eventId: s.getEventId(),
              station: s.getStation(),
              scannerId: s.getScannerId(),
              scannedAtMs: toMs(s.getScannedAt()),
              result: s.getResult(),
              damageType: s.getDamageType(),
              damageConfidence: s.getDamageConfidence(),
            })),
            alerts: response.getAlertsList().map((a) => {
              const item: JourneyAlert = {
                alertId: a.getAlertId(),
                alertType: a.getAlertType(),
                severity: a.getSeverity(),
                station: a.getStation(),
                message: a.getMessage(),
                detectedAtMs: toMs(a.getDetectedAt()),
              };
              if (a.hasStuckDetail()) {
                const d = a.getStuckDetail()!;
                item.stuckDetail = {
                  stuckDurationSeconds: d.getStuckDurationSeconds(),
                  thresholdSeconds: d.getThresholdSeconds(),
                };
              } else if (a.hasMisroutingDetail()) {
                const d = a.getMisroutingDetail()!;
                item.misroutingDetail = {
                  expectedStation: d.getExpectedStation(),
                  actualStation: d.getActualStation(),
                  pathSoFar: d.getPathSoFarList(),
                };
              } else if (a.hasDamageDetail()) {
                const d = a.getDamageDetail()!;
                item.damageDetail = {
                  damageType: d.getDamageType(),
                  confidence: d.getConfidence(),
                  imageRef: d.getImageRef(),
                };
              }
              return item;
            }),
          });
          setStatus("loaded");
        })
        .catch(() => {
          if (!cancelled) setStatus("error");
        });
    }

    fetchJourney();

    return () => {
      cancelled = true;
    };
  }, [packageId]);

  return { journey, status };
}
