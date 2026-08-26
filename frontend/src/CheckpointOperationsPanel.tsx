import type { AlertItem, PackagePosition } from "./useLiveFeed";
import { useStationStats } from "./useStationStats";
import { STATION_LABEL, ALERT_TYPE_ICON, ALERT_TYPE_LABEL, timeAgo, type StationType } from "./constants";
import StationIcon, { type StationVisualState } from "./StationIcon";
import { Button } from "@/components/ui/button";
import { LineChart, BarChart } from "./charts";
import "./JourneyPanel.css";
import "./CheckpointOperationsPanel.css";

// Mirrors useFloorPlanTracking.ts's DELAYED_THRESHOLD_MS/STUCK_THRESHOLD_MS —
// scoped here to one station's package list instead of the whole
// facility. Duplicated (not imported) since useFloorPlanTracking
// doesn't export these; same "intentionally mirrored constant"
// convention already used there for the backend's STUCK_THRESHOLD_MS.
const DELAYED_THRESHOLD_MS = 5 * 60 * 1000;
const STUCK_THRESHOLD_MS = 10 * 60 * 1000;

interface CheckpointOperationsPanelProps {
  station: StationType;
  packages: PackagePosition[];
  stationState: StationVisualState;
  alerts: AlertItem[];
  now: number;
  onClose: () => void;
  onViewInTrends: () => void;
}

const MAX_ALERTS_SHOWN = 10;
const MAX_PACKAGES_SHOWN = 12;

function CheckpointOperationsPanel({
  station,
  packages,
  stationState,
  alerts,
  now,
  onClose,
  onViewInTrends,
}: CheckpointOperationsPanelProps) {
  const { stats, status } = useStationStats(station);

  const stationAlerts = alerts
    .filter((a) => a.station === station)
    .sort((a, b) => b.detectedAtMs - a.detectedAtMs)
    .slice(0, MAX_ALERTS_SHOWN);

  let delayedCount = 0;
  let atRiskCount = 0;
  for (const p of packages) {
    const dwell = now - p.updatedAtMs;
    if (dwell >= STUCK_THRESHOLD_MS * 0.8 && dwell < STUCK_THRESHOLD_MS) atRiskCount++;
    else if (dwell >= DELAYED_THRESHOLD_MS) delayedCount++;
  }

  return (
    <div className="journey-overlay" onClick={onClose}>
      <aside className="journey-panel checkpoint-ops-panel" onClick={(e) => e.stopPropagation()}>
        <div className="journey-header">
          <div className="journey-eyebrow">Checkpoint operations</div>
          <button className="journey-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="checkpoint-title-row">
          <span className="checkpoint-icon-wrap">
            <StationIcon station={station} state={stationState} />
          </span>
          <h2 className="journey-id">{STATION_LABEL[station] ?? "Unknown station"}</h2>
        </div>

        {stationState !== "normal" && (
          <span className={`journey-status-badge ${stationState}`}>{stationState}</span>
        )}

        <div className="checkpoint-live-stats">
          <div className="checkpoint-stat">
            <span className="checkpoint-stat-value">{packages.length}</span>
            <span className="checkpoint-stat-label">Occupancy</span>
          </div>
          <div className="checkpoint-stat">
            <span className="checkpoint-stat-value">{delayedCount}</span>
            <span className="checkpoint-stat-label">Delayed</span>
          </div>
          <div className="checkpoint-stat">
            <span className="checkpoint-stat-value">{atRiskCount}</span>
            <span className="checkpoint-stat-label">At risk</span>
          </div>
        </div>

        <h3 className="checkpoint-section-title">Packages here now</h3>
        {packages.length === 0 && <div className="journey-empty">Nothing at this station right now.</div>}
        {packages.length > 0 && (
          <ul className="checkpoint-package-list">
            {packages.slice(0, MAX_PACKAGES_SHOWN).map((p) => (
              <li key={p.packageId} className="checkpoint-package-row">
                <span className="checkpoint-package-name">
                  {p.itemName || `Package ${p.packageId.slice(0, 8)}`}
                </span>
                <span className="checkpoint-package-time">{timeAgo(p.updatedAtMs)}</span>
              </li>
            ))}
            {packages.length > MAX_PACKAGES_SHOWN && (
              <li className="checkpoint-package-overflow">+{packages.length - MAX_PACKAGES_SHOWN} more</li>
            )}
          </ul>
        )}

        <h3 className="checkpoint-section-title">Recent alerts here</h3>
        {stationAlerts.length === 0 && <div className="journey-empty">No alerts this session.</div>}
        {stationAlerts.length > 0 && (
          <div className="checkpoint-alert-list">
            {stationAlerts.map((a) => (
              <div key={`${a.alertId}-${a.detectedAtMs}`} className="timeline-alert">
                <span className="timeline-alert-icon" aria-hidden="true">
                  {ALERT_TYPE_ICON[a.alertType] ?? "?"}
                </span>
                <div>
                  <div className="timeline-alert-title">
                    {ALERT_TYPE_LABEL[a.alertType] ?? "Alert"}, {timeAgo(a.detectedAtMs)}
                  </div>
                  <div className="timeline-alert-message">{a.message}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        <h3 className="checkpoint-section-title">Throughput today</h3>
        {status === "loading" && <div className="journey-loading">Loading history…</div>}
        {status === "error" && <div className="journey-error">Couldn't load station history.</div>}
        {status === "loaded" && stats && (
          <>
            <LineChart
              points={stats.throughputSeries.map((p) => ({
                label: new Date(p.bucketMs).toLocaleDateString(),
                value: p.count,
              }))}
              emptyHint="No batch report for this range yet — the daily throughput job hasn't run."
            />
            <div className="checkpoint-live-stats">
              <div className="checkpoint-stat">
                <span className="checkpoint-stat-value">{(stats.damageRate * 100).toFixed(1)}%</span>
                <span className="checkpoint-stat-label">Damage rate</span>
              </div>
            </div>
            <h3 className="checkpoint-section-title">Alert breakdown</h3>
            <BarChart
              data={stats.alertBreakdown.map((a) => ({
                label: ALERT_TYPE_LABEL[a.alertType] ?? "Unknown",
                value: a.count,
              }))}
              valueFmt={(v) => v.toLocaleString()}
            />
          </>
        )}

        <Button variant="outline" className="checkpoint-view-trends" onClick={onViewInTrends}>
          View in Trends →
        </Button>
      </aside>
    </div>
  );
}

export default CheckpointOperationsPanel;
