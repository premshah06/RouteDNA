// See useLiveFeed.ts for why these are namespace imports.
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";

const { StationType } = commonPb;
const { AlertType, Severity } = alertPb;
export type StationType = commonPb.StationType;

// Order matches the facility's real linear routing chain (see
// services/ingestion/server.py's _NEXT_STATION and
// stream_processing/jobs/journey_correlator.py's EXPECTED_PATH) — every
// package passes through all seven, in this order, no branching.
export const STATIONS: { type: StationType; label: string }[] = [
  { type: StationType.STATION_TYPE_INTAKE, label: "Intake" },
  { type: StationType.STATION_TYPE_INDUCTION, label: "Induction" },
  { type: StationType.STATION_TYPE_SORT_A, label: "Sort A" },
  { type: StationType.STATION_TYPE_SORT_B, label: "Sort B" },
  { type: StationType.STATION_TYPE_QC_CHECK, label: "QC Check" },
  { type: StationType.STATION_TYPE_STAGING, label: "Staging" },
  { type: StationType.STATION_TYPE_DISPATCH, label: "Dispatch" },
];

export const STATION_LABEL: Record<number, string> = Object.fromEntries(
  STATIONS.map((s) => [s.type, s.label])
);

// Matches proto/packagepb/v1/item.proto's ItemCategory enum values —
// same numbering packageGlyphs.ts's PACKAGE_GLYPHS/PACKAGE_COLORS use.
export const ITEM_CATEGORY_LABEL: Record<number, string> = {
  0: "Other",
  1: "Electronics",
  2: "Apparel",
  3: "Home Goods",
  4: "Grocery",
  5: "Books & Media",
  6: "Toys",
  7: "Health & Beauty",
  8: "Automotive",
  9: "Other",
};

export const ALERT_TYPE_LABEL: Record<number, string> = {
  [AlertType.ALERT_TYPE_UNSPECIFIED]: "Unknown",
  [AlertType.ALERT_TYPE_STUCK_PACKAGE]: "Stuck",
  [AlertType.ALERT_TYPE_DAMAGE]: "Damage",
  [AlertType.ALERT_TYPE_MISROUTING]: "Misrouted",
};

// One glance should say which of the platform's three failure modes
// this is — the whole point of this dashboard (see README) — without
// reading the label text.
export const ALERT_TYPE_ICON: Record<number, string> = {
  [AlertType.ALERT_TYPE_UNSPECIFIED]: "?",
  [AlertType.ALERT_TYPE_STUCK_PACKAGE]: "⏱",
  [AlertType.ALERT_TYPE_DAMAGE]: "⚠",
  [AlertType.ALERT_TYPE_MISROUTING]: "⇄",
};

export const SEVERITY_LABEL: Record<number, string> = {
  [Severity.SEVERITY_UNSPECIFIED]: "unspecified",
  [Severity.SEVERITY_INFO]: "info",
  [Severity.SEVERITY_WARNING]: "warning",
  [Severity.SEVERITY_CRITICAL]: "critical",
};

// Matches proto/packagepb/v1/scan_event.proto's DamageType enum.
export const DAMAGE_TYPE_LABEL: Record<number, string> = {
  0: "Unspecified",
  1: "Crushed",
  2: "Torn",
  3: "Wet",
  4: "Leaking",
  5: "Other",
};

export function timeAgo(ms: number): string {
  const seconds = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}
