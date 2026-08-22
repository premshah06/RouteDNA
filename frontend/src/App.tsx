import { useMemo } from "react";
import { useLiveFeed, type PackagePosition } from "./useLiveFeed";
// See useLiveFeed.ts for why this must be a namespace import.
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";
import "./App.css";

const { StationType } = commonPb;
const { AlertType, Severity } = alertPb;
type StationType = commonPb.StationType;

const STATIONS: { type: StationType; label: string }[] = [
  { type: StationType.STATION_TYPE_INTAKE, label: "Intake" },
  { type: StationType.STATION_TYPE_SORT_A, label: "Sort A" },
  { type: StationType.STATION_TYPE_SORT_B, label: "Sort B" },
  { type: StationType.STATION_TYPE_DISPATCH, label: "Dispatch" },
];

const ALERT_TYPE_LABEL: Record<number, string> = {
  [AlertType.ALERT_TYPE_UNSPECIFIED]: "Unknown",
  [AlertType.ALERT_TYPE_STUCK_PACKAGE]: "Stuck",
  [AlertType.ALERT_TYPE_DAMAGE]: "Damage",
  [AlertType.ALERT_TYPE_MISROUTING]: "Misrouted",
};

const SEVERITY_LABEL: Record<number, string> = {
  [Severity.SEVERITY_UNSPECIFIED]: "unspecified",
  [Severity.SEVERITY_INFO]: "info",
  [Severity.SEVERITY_WARNING]: "warning",
  [Severity.SEVERITY_CRITICAL]: "critical",
};

function timeAgo(ms: number): string {
  const seconds = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function App() {
  const { positions, alerts, status } = useLiveFeed();

  const packagesByStation = useMemo(() => {
    const grouped = new Map<StationType, PackagePosition[]>();
    for (const station of STATIONS) grouped.set(station.type, []);
    for (const position of positions.values()) {
      const list = grouped.get(position.station);
      if (list) list.push(position);
    }
    return grouped;
  }, [positions]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Facility Live View</h1>
        <span className={`status-badge status-${status}`}>{status}</span>
      </header>

      <main className="facility">
        {STATIONS.map((station) => {
          const packages = packagesByStation.get(station.type) ?? [];
          return (
            <section key={station.type} className="station-lane">
              <h2>
                {station.label}
                <span className="count">{packages.length}</span>
              </h2>
              <ul className="package-list">
                {packages.map((p) => (
                  <li key={p.packageId} className="package-chip" title={p.packageId}>
                    <span className="package-id">{p.packageId.slice(0, 8)}</span>
                    <span className="package-time">{timeAgo(p.updatedAtMs)}</span>
                  </li>
                ))}
                {packages.length === 0 && <li className="empty">—</li>}
              </ul>
            </section>
          );
        })}
      </main>

      <aside className="alerts-panel">
        <h2>Alerts</h2>
        <ul className="alerts-list">
          {alerts.map((alert) => (
            <li key={`${alert.alertId}-${alert.detectedAtMs}`} className={`alert-item severity-${SEVERITY_LABEL[alert.severity]}`}>
              <div className="alert-header">
                <span className="alert-type">{ALERT_TYPE_LABEL[alert.alertType] ?? "Alert"}</span>
                <span className="alert-time">{timeAgo(alert.detectedAtMs)}</span>
              </div>
              <div className="alert-message">{alert.message}</div>
              <div className="alert-package" title={alert.packageId}>
                {alert.packageId.slice(0, 8)}
              </div>
            </li>
          ))}
          {alerts.length === 0 && <li className="empty">No alerts yet</li>}
        </ul>
      </aside>
    </div>
  );
}

export default App;
