import type { AlertItem } from "./useLiveFeed";
import { usePackageJourney, type JourneyAlert } from "./usePackageJourney";
import {
  ALERT_TYPE_ICON,
  ALERT_TYPE_LABEL,
  DAMAGE_TYPE_LABEL,
  SEVERITY_LABEL,
  STATION_LABEL,
  timeAgo,
} from "./constants";
import { Button } from "@/components/ui/button";
import "./ExceptionCase.css";

interface ExceptionCaseProps {
  alert: AlertItem;
  itemName?: string;
  onClose: () => void;
  onOpenJourney: () => void;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

// The alert as first clicked only has full detail if it came live off
// the stream (AlertsPanel) — one opened from a historical row (Trends)
// only has the flat fields until GetPackageJourney's alerts list comes
// back with the same detail persisted server-side. Prefer whichever
// has detail already.
//
// Historical rows are seeded with a synthetic alertId
// (`seed-${packageId}-${detectedAtMs}`, see App.tsx's
// flaggedParcelToAlertItem) that never matches the real alertId
// GetPackageJourney returns — matching by (alertType, detectedAtMs)
// instead, since those two together are what the seed was built from
// and are stable across both sources for the same underlying alert.
function pickDetailedAlert(initial: AlertItem, fromJourney: JourneyAlert[] | undefined): AlertItem | JourneyAlert {
  if (initial.stuckDetail || initial.misroutingDetail || initial.damageDetail) return initial;
  const match = fromJourney?.find(
    (a) => a.alertType === initial.alertType && Math.abs(a.detectedAtMs - initial.detectedAtMs) < 1000
  );
  return match ?? initial;
}

function ExceptionCase({ alert: initialAlert, itemName, onClose, onOpenJourney }: ExceptionCaseProps) {
  const { journey, status } = usePackageJourney(initialAlert.packageId);
  const alert = pickDetailedAlert(initialAlert, journey?.alerts);

  // Real scan history immediately around the alert's own timestamp —
  // the honest substitute for "queue depth at the time," which no
  // table in this system tracks.
  const nearbyScans = (journey?.scans ?? [])
    .filter((s) => Math.abs(s.scannedAtMs - initialAlert.detectedAtMs) < 30 * 60 * 1000)
    .sort((a, b) => a.scannedAtMs - b.scannedAtMs);

  return (
    <div className="journey-overlay" onClick={onClose}>
      <aside className="exception-case" onClick={(e) => e.stopPropagation()}>
        <div className="journey-header">
          <div className="journey-eyebrow">Exception case</div>
          <button className="journey-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="case-title-row">
          <span className="case-icon-badge" aria-hidden="true">
            {ALERT_TYPE_ICON[initialAlert.alertType] ?? "?"}
          </span>
          <div>
            <h2 className="journey-id">{ALERT_TYPE_LABEL[initialAlert.alertType] ?? "Alert"}</h2>
            <div className="case-subtitle">{itemName || `Package ${initialAlert.packageId.slice(0, 8)}`}</div>
          </div>
        </div>
        <div className="journey-id-full" title={initialAlert.packageId}>{initialAlert.packageId}</div>

        <span className={`journey-status-badge ${SEVERITY_LABEL[initialAlert.severity]}`}>
          {SEVERITY_LABEL[initialAlert.severity]}
        </span>
        <div className="case-detected-at">Detected {timeAgo(initialAlert.detectedAtMs)}</div>
        <div className="case-message">{initialAlert.message}</div>

        {alert.stuckDetail && (
          <div className="case-detail-block">
            <h3>Dwell vs. threshold</h3>
            <div className="case-compare">
              <div className="case-compare-row">
                <span className="case-compare-label">Stuck for</span>
                <span className="case-compare-value critical">
                  {formatDuration(alert.stuckDetail.stuckDurationSeconds)}
                </span>
              </div>
              <div className="case-compare-track">
                <div
                  className="case-compare-fill critical"
                  style={{
                    width: `${Math.min(
                      100,
                      (alert.stuckDetail.stuckDurationSeconds /
                        Math.max(alert.stuckDetail.stuckDurationSeconds, alert.stuckDetail.thresholdSeconds)) *
                        100
                    )}%`,
                  }}
                />
              </div>
              <div className="case-compare-row">
                <span className="case-compare-label">Threshold</span>
                <span className="case-compare-value">{formatDuration(alert.stuckDetail.thresholdSeconds)}</span>
              </div>
              <div className="case-compare-track">
                <div
                  className="case-compare-fill"
                  style={{
                    width: `${Math.min(
                      100,
                      (alert.stuckDetail.thresholdSeconds /
                        Math.max(alert.stuckDetail.stuckDurationSeconds, alert.stuckDetail.thresholdSeconds)) *
                        100
                    )}%`,
                  }}
                />
              </div>
            </div>
            <div className="case-overage">
              {alert.stuckDetail.stuckDurationSeconds > alert.stuckDetail.thresholdSeconds
                ? `${formatDuration(alert.stuckDetail.stuckDurationSeconds - alert.stuckDetail.thresholdSeconds)} past threshold`
                : "Within threshold"}
            </div>
          </div>
        )}

        {alert.misroutingDetail && (
          <div className="case-detail-block">
            <h3>Route</h3>
            <div className="case-route-compare">
              <div>
                <div className="case-route-label">Expected</div>
                <div className="case-route-station">{STATION_LABEL[alert.misroutingDetail.expectedStation] ?? "—"}</div>
              </div>
              <div className="case-route-arrow">→</div>
              <div>
                <div className="case-route-label">Actual</div>
                <div className="case-route-station critical">
                  {STATION_LABEL[alert.misroutingDetail.actualStation] ?? "—"}
                </div>
              </div>
            </div>
            {alert.misroutingDetail.pathSoFar.length > 0 && (
              <>
                <h3>Path so far</h3>
                <div className="case-path-trail">
                  {alert.misroutingDetail.pathSoFar.map((station, i) => (
                    <span key={i} className="case-path-chip">
                      {STATION_LABEL[station] ?? "Unknown"}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {alert.damageDetail && (
          <div className="case-detail-block">
            <h3>Damage assessment</h3>
            <div className="case-compare-row">
              <span className="case-compare-label">Type</span>
              <span className="case-compare-value">{DAMAGE_TYPE_LABEL[alert.damageDetail.damageType] ?? "Unknown"}</span>
            </div>
            <div className="case-compare-row">
              <span className="case-compare-label">Confidence</span>
              <span className="case-compare-value">{(alert.damageDetail.confidence * 100).toFixed(0)}%</span>
            </div>
            {alert.damageDetail.imageRef && (
              <div className="case-compare-row">
                <span className="case-compare-label">Image ref</span>
                <span className="case-compare-value case-image-ref">{alert.damageDetail.imageRef}</span>
              </div>
            )}
          </div>
        )}

        <div className="case-detail-block">
          <h3>Scans around this alert</h3>
          {status === "loading" && <div className="journey-loading">Loading scan history…</div>}
          {status === "loaded" && nearbyScans.length === 0 && (
            <div className="journey-empty">No scans within 30 minutes of this alert.</div>
          )}
          {status === "loaded" && nearbyScans.length > 0 && (
            <div className="journey-timeline">
              {nearbyScans.map((s) => (
                <div key={s.eventId} className="timeline-step">
                  <div className="timeline-marker" />
                  <div className="timeline-body">
                    <div className="timeline-title">
                      {STATION_LABEL[s.station] ?? "Unknown station"}
                      <span className="timeline-time">{timeAgo(s.scannedAtMs)}</span>
                    </div>
                    <div className="timeline-detail">
                      Scanner {s.scannerId} · {s.result.replace("SCAN_RESULT_", "")}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <Button variant="outline" className="case-full-journey-link" onClick={onOpenJourney}>
          View full package journey →
        </Button>
      </aside>
    </div>
  );
}

export default ExceptionCase;
