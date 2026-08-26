import { useCallback, useState } from "react";
import type { AlertItem, PackagePosition } from "./useLiveFeed";
import type { StationType } from "./constants";
import { useFloorPlanTracking } from "./useFloorPlanTracking";
import { Card, CardContent } from "@/components/ui/card";
import FloorPlan from "./FloorPlan";
import PackageTooltip from "./PackageTooltip";
import QueueDepthPanel from "./QueueDepthPanel";
import ScanEventFeed from "./ScanEventFeed";
import CheckpointOperationsPanel from "./CheckpointOperationsPanel";
import "./LiveView.css";

interface KpiStripProps {
  inTransit: number;
  throughputTotal: number;
  damageRate: number;
  delayedCount: number;
  atRiskCount: number;
}

function KpiStrip({ inTransit, throughputTotal, damageRate, delayedCount, atRiskCount }: KpiStripProps) {
  const kpis = [
    { value: inTransit, label: "In transit" },
    { value: throughputTotal.toLocaleString(), label: "Throughput today" },
    { value: `${(damageRate * 100).toFixed(1)}%`, label: "Damage rate" },
    { value: delayedCount, label: "Delayed parcels" },
    { value: atRiskCount, label: "SLA at risk" },
  ];
  return (
    <div className="kpi-strip">
      {kpis.map((k) => (
        <Card key={k.label} className="kpi bg-transparent p-0 ring-0">
          <CardContent className="p-0">
            <span className="kpi-value">{k.value}</span>
            <span className="kpi-label">{k.label}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

interface LiveViewProps {
  positions: Map<string, PackagePosition>;
  alerts: AlertItem[];
  throughputTotal: number;
  damageRate: number;
  recentEvents: PackagePosition[];
  onSelectPackage: (packageId: string) => void;
  focusedStation: StationType | null;
  onFocusStation: (station: StationType) => void;
}

function LiveView({
  positions,
  alerts,
  throughputTotal,
  damageRate,
  recentEvents,
  onSelectPackage,
  focusedStation,
  onFocusStation,
}: LiveViewProps) {
  const { now, activeTravelers, stationState, packagesByStation, delayedCount, atRiskCount } = useFloorPlanTracking(
    positions,
    alerts
  );

  const [hovered, setHovered] = useState<{
    packageId: string;
    anchor: { x: number; y: number };
  } | null>(null);

  const handleHover = useCallback((packageId: string | null, anchor: { x: number; y: number } | null) => {
    if (packageId && anchor) setHovered({ packageId, anchor });
    else setHovered(null);
  }, []);

  const hoveredPosition = hovered ? positions.get(hovered.packageId) : undefined;

  // Owned here (not lifted to App.tsx) since nothing outside the Live
  // tab needs to open this panel, and it needs useFloorPlanTracking's
  // derived data, which also lives only in this component.
  const [selectedStation, setSelectedStation] = useState<StationType | null>(null);

  return (
    <div className="live-view">
      <KpiStrip
        inTransit={positions.size}
        throughputTotal={throughputTotal}
        damageRate={damageRate}
        delayedCount={delayedCount}
        atRiskCount={atRiskCount}
      />
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
            onOpenStation={setSelectedStation}
          />
        </div>
      </div>
      {hovered && hoveredPosition && (
        <PackageTooltip position={hoveredPosition} alerts={alerts} anchor={hovered.anchor} />
      )}
      <div className="live-bottom-row">
        <QueueDepthPanel packagesByStation={packagesByStation} />
        <ScanEventFeed events={recentEvents} />
      </div>
      {selectedStation !== null && (
        <CheckpointOperationsPanel
          station={selectedStation}
          packages={packagesByStation.get(selectedStation) ?? []}
          stationState={stationState.get(selectedStation) ?? "normal"}
          alerts={alerts}
          now={now}
          onClose={() => setSelectedStation(null)}
          onViewInTrends={() => {
            onFocusStation(selectedStation);
            setSelectedStation(null);
          }}
        />
      )}
    </div>
  );
}

export default LiveView;
