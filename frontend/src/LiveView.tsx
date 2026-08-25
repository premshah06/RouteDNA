import { useState } from "react";
import type { AlertItem, PackagePosition } from "./useLiveFeed";
import type { StationType } from "./constants";
import { useFloorPlanTracking } from "./useFloorPlanTracking";
import FloorPlan from "./FloorPlan";
import PackageTooltip from "./PackageTooltip";
import "./LiveView.css";

interface KpiStripProps {
  inTransit: number;
  throughputTotal: number;
  damageRate: number;
}

function KpiStrip({ inTransit, throughputTotal, damageRate }: KpiStripProps) {
  return (
    <div className="kpi-strip">
      <div className="kpi">
        <span className="kpi-value">{inTransit}</span>
        <span className="kpi-label">In transit</span>
      </div>
      <div className="kpi">
        <span className="kpi-value">{throughputTotal.toLocaleString()}</span>
        <span className="kpi-label">Throughput today</span>
      </div>
      <div className="kpi">
        <span className="kpi-value">{(damageRate * 100).toFixed(1)}%</span>
        <span className="kpi-label">Damage rate</span>
      </div>
    </div>
  );
}

interface LiveViewProps {
  positions: Map<string, PackagePosition>;
  alerts: AlertItem[];
  throughputTotal: number;
  damageRate: number;
  onSelectPackage: (packageId: string) => void;
  focusedStation: StationType | null;
  onFocusStation: (station: StationType) => void;
}

function LiveView({
  positions,
  alerts,
  throughputTotal,
  damageRate,
  onSelectPackage,
  focusedStation,
  onFocusStation,
}: LiveViewProps) {
  const { now, activeTravelers, stationState, packagesByStation } = useFloorPlanTracking(positions, alerts);

  const [hovered, setHovered] = useState<{
    packageId: string;
    anchor: { x: number; y: number };
  } | null>(null);

  const handleHover = (packageId: string | null, anchor: { x: number; y: number } | null) => {
    if (packageId && anchor) setHovered({ packageId, anchor });
    else setHovered(null);
  };

  const hoveredPosition = hovered ? positions.get(hovered.packageId) : undefined;

  return (
    <div className="live-view">
      <KpiStrip inTransit={positions.size} throughputTotal={throughputTotal} damageRate={damageRate} />
      <div className="facility-canvas-wrap">
        <div className="facility-canvas">
          <FloorPlan
            packagesByStation={packagesByStation}
            activeTravelers={activeTravelers}
            stationState={stationState}
            now={now}
            onSelectPackage={onSelectPackage}
            onHoverPackage={handleHover}
            focusedStation={focusedStation}
            onFocusStation={onFocusStation}
          />
        </div>
      </div>
      {hovered && hoveredPosition && (
        <PackageTooltip position={hoveredPosition} alerts={alerts} anchor={hovered.anchor} />
      )}
    </div>
  );
}

export default LiveView;
