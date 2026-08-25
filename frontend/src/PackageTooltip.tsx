import type { AlertItem, PackagePosition } from "./useLiveFeed";
import { ALERT_TYPE_LABEL, SEVERITY_LABEL, STATION_LABEL, timeAgo } from "./constants";
import PackageIcon from "./PackageIcon";
import "./PackageTooltip.css";

interface PackageTooltipProps {
  position: PackagePosition;
  alerts: AlertItem[];
  anchor: { x: number; y: number };
}

// Fast preview on hover — everything here comes from data already in
// memory (the live positions map + recent alerts), no extra RPC, so it
// can render instantly on mouseenter. Deeper history (scan timeline,
// full alert detail) stays behind a click into JourneyPanel, which
// does fetch via QueryService.
function PackageTooltip({ position, alerts, anchor }: PackageTooltipProps) {
  const packageAlerts = alerts.filter((a) => a.packageId === position.packageId);
  const worstAlert = packageAlerts.reduce<AlertItem | null>((worst, a) => {
    if (!worst) return a;
    return a.severity > worst.severity ? a : worst;
  }, null);

  return (
    <div
      className="package-tooltip"
      style={{ left: anchor.x + 14, top: anchor.y + 14 }}
    >
      <div className="package-tooltip-header">
        <PackageIcon category={position.itemCategory} className="package-tooltip-icon" />
        <span className="package-tooltip-name">
          {position.itemName || `Package ${position.packageId.slice(0, 8)}`}
        </span>
      </div>
      <div className="package-tooltip-id">{position.packageId}</div>
      <div className="package-tooltip-row">
        <span className="package-tooltip-label">Station</span>
        <span>{STATION_LABEL[position.station] ?? "Unknown"}</span>
      </div>
      <div className="package-tooltip-row">
        <span className="package-tooltip-label">Since</span>
        <span>{timeAgo(position.updatedAtMs)}</span>
      </div>
      {worstAlert && (
        <div className={`package-tooltip-alert severity-${SEVERITY_LABEL[worstAlert.severity]}`}>
          {ALERT_TYPE_LABEL[worstAlert.alertType] ?? "Alert"}
        </div>
      )}
    </div>
  );
}

export default PackageTooltip;
