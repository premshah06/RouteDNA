import { useEffect, useState } from "react";
import type { AlertItem } from "./useLiveFeed";
import type { PackagePosition } from "./useLiveFeed";
import { ALERT_TYPE_ICON, ALERT_TYPE_LABEL, SEVERITY_LABEL, timeAgo } from "./constants";
import "./AlertsPanel.css";

interface AlertsPanelProps {
  alerts: AlertItem[];
  positions: Map<string, PackagePosition>;
  onSelectPackage: (packageId: string) => void;
}

const JUST_NOW_MS = 2 * 60 * 1000;

function alertKey(alert: AlertItem): string {
  return `${alert.alertId}-${alert.detectedAtMs}`;
}

function AlertsPanel({ alerts, positions, onSelectPackage }: AlertsPanelProps) {
  // Committed (as of the last render this effect ran after) set of
  // alert keys already seen — only alerts absent from this set get the
  // slide-in entrance animation. Updated in an effect, not during
  // render, so the render itself stays a pure read of committed state
  // rather than mutating a ref as a side effect of rendering.
  const [knownKeys, setKnownKeys] = useState<Set<string>>(new Set());
  useEffect(() => {
    setKnownKeys((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const alert of alerts) {
        const key = alertKey(alert);
        if (!next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [alerts]);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // Re-renders periodically purely so "Just now" -> "Earlier" grouping
    // advances on its own, the same pattern LiveView uses for its own
    // time-relative UI.
    const interval = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(interval);
  }, []);

  const justNow = alerts.filter((a) => now - a.detectedAtMs < JUST_NOW_MS);
  const earlier = alerts.filter((a) => now - a.detectedAtMs >= JUST_NOW_MS);

  function renderAlert(alert: AlertItem) {
    const key = alertKey(alert);
    const isNew = !knownKeys.has(key);
    const itemName = positions.get(alert.packageId)?.itemName;
    return (
      <li
        key={key}
        className={`alert-item severity-${SEVERITY_LABEL[alert.severity]}${isNew ? " alert-item-enter" : ""}`}
        onClick={() => onSelectPackage(alert.packageId)}
      >
        <div className="alert-icon-badge" aria-hidden="true">
          {ALERT_TYPE_ICON[alert.alertType] ?? "?"}
        </div>
        <div className="alert-body">
          <div className="alert-header">
            <span className="alert-type">{ALERT_TYPE_LABEL[alert.alertType] ?? "Alert"}</span>
            <span className="alert-time">{timeAgo(alert.detectedAtMs)}</span>
          </div>
          <div className="alert-message">{alert.message}</div>
          <div className="alert-package" title={alert.packageId}>
            {itemName || `Package ${alert.packageId.slice(0, 8)}`}
          </div>
        </div>
      </li>
    );
  }

  return (
    <aside className="alerts-panel">
      <h2>Alerts</h2>
      {justNow.length > 0 && (
        <>
          <div className="alerts-group-label">Just now</div>
          <ul className="alerts-list">{justNow.map(renderAlert)}</ul>
        </>
      )}
      {earlier.length > 0 && (
        <>
          <div className="alerts-group-label">Earlier</div>
          <ul className="alerts-list">{earlier.map(renderAlert)}</ul>
        </>
      )}
      {alerts.length === 0 && <div className="empty">No alerts yet</div>}
    </aside>
  );
}

export default AlertsPanel;
