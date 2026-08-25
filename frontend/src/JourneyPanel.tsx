import { usePackageJourney } from "./usePackageJourney";
import { ALERT_TYPE_ICON, ALERT_TYPE_LABEL, SEVERITY_LABEL, STATION_LABEL, timeAgo } from "./constants";
import "./JourneyPanel.css";

interface JourneyPanelProps {
  packageId: string;
  itemName?: string;
  onClose: () => void;
}

function JourneyPanel({ packageId, itemName, onClose }: JourneyPanelProps) {
  const { journey, status } = usePackageJourney(packageId);

  // Interleave scans and alerts into one chronological timeline —
  // an alert is shown attached after the scan at the same station it
  // concerns, since that's the scan that triggered it.
  const timelineEntries = journey
    ? [
        ...journey.scans.map((s) => ({ kind: "scan" as const, atMs: s.scannedAtMs, scan: s })),
        ...journey.alerts.map((a) => ({ kind: "alert" as const, atMs: a.detectedAtMs, alert: a })),
      ].sort((a, b) => a.atMs - b.atMs)
    : [];

  const hasCritical = journey?.alerts.some((a) => SEVERITY_LABEL[a.severity] === "critical");
  const hasWarning = journey?.alerts.some((a) => SEVERITY_LABEL[a.severity] === "warning");

  return (
    <div className="journey-overlay" onClick={onClose}>
      <aside className="journey-panel" onClick={(e) => e.stopPropagation()}>
        <div className="journey-header">
          <div className="journey-eyebrow">Parcel journey</div>
          <button className="journey-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <h2 className="journey-id">{itemName || `Package ${packageId.slice(0, 8)}`}</h2>
        <div className="journey-id-full" title={packageId}>{packageId}</div>

        {(hasCritical || hasWarning) && (
          <span className={`journey-status-badge ${hasCritical ? "critical" : "warning"}`}>
            {hasCritical ? "Flagged" : "Warning"}
          </span>
        )}

        {status === "loading" && <div className="journey-loading">Loading journey…</div>}
        {status === "error" && <div className="journey-error">Couldn't load journey history.</div>}

        {status === "loaded" && journey && (
          <div className="journey-timeline">
            {timelineEntries.length === 0 && <div className="journey-empty">No scan history yet.</div>}
            {timelineEntries.map((entry, i) =>
              entry.kind === "scan" ? (
                <div key={`scan-${entry.scan.eventId}`} className="timeline-step">
                  <div className="timeline-marker" />
                  <div className="timeline-body">
                    <div className="timeline-title">
                      {STATION_LABEL[entry.scan.station] ?? "Unknown station"}
                      <span className="timeline-time">{timeAgo(entry.atMs)}</span>
                    </div>
                    <div className="timeline-detail">
                      Scanner {entry.scan.scannerId} · {entry.scan.result.replace("SCAN_RESULT_", "")}
                    </div>
                  </div>
                </div>
              ) : (
                <div key={`alert-${entry.alert.alertId}-${i}`} className="timeline-alert">
                  <span className="timeline-alert-icon" aria-hidden="true">
                    {ALERT_TYPE_ICON[entry.alert.alertType] ?? "?"}
                  </span>
                  <div>
                    <div className="timeline-alert-title">
                      {ALERT_TYPE_LABEL[entry.alert.alertType] ?? "Alert"}, {timeAgo(entry.atMs)}
                    </div>
                    <div className="timeline-alert-message">{entry.alert.message}</div>
                  </div>
                </div>
              )
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

export default JourneyPanel;
