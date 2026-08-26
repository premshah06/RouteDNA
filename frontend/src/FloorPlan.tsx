import { useCallback, useMemo } from "react";
import { ReactFlow, type Node, type NodeTypes, type NodeMouseHandler, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { PackagePosition } from "./useLiveFeed";
import { STATIONS, type StationType } from "./constants";
import StationIcon, { type StationVisualState } from "./StationIcon";
import { PACKAGE_COLORS, PACKAGE_GLYPHS } from "./packageGlyphs";
import type { Traveler } from "./useFloorPlanTracking";
import { TRAVEL_MS } from "./useFloorPlanTracking";
import "./FloorPlan.css";

// Same fixed-diagram basis the old SVG version used — a wide flow-path
// strip matching .facility-canvas's aspect-ratio (1180/420), not a
// full-bleed pannable graph.
const CANVAS_WIDTH = 1180;
const CANVAS_HEIGHT = 420;
const ZONE_WIDTH = 138;
const ZONE_TOP = 60;
const ZONE_HEIGHT = 320;
const ZONE_GAP = (CANVAS_WIDTH - STATIONS.length * ZONE_WIDTH) / (STATIONS.length + 1);
const SPINE_Y = ZONE_TOP + ZONE_HEIGHT / 2;

function zoneCenterX(index: number): number {
  return ZONE_GAP + index * (ZONE_WIDTH + ZONE_GAP) + ZONE_WIDTH / 2;
}

// Deterministic pseudo-random offset so a station's packages spread out
// across its zone instead of stacking on one pixel — a layout position
// for legibility, not a claim about real physical placement on the belt.
function jitter(packageId: string, spread: number): number {
  let hash = 0;
  for (let i = 0; i < packageId.length; i++) {
    hash = (hash * 31 + packageId.charCodeAt(i)) | 0;
  }
  return ((Math.abs(hash) % 1000) / 1000 - 0.5) * spread;
}

// A bare glyph path sized for the small dot radius used on the floor
// plan — PackageIcon renders its own <svg> root which can't nest here.
function PackageIconGlyph({ category }: { category: number }) {
  const d = PACKAGE_GLYPHS[category] ?? PACKAGE_GLYPHS[0];
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" className="floor-plan-dot-glyph-svg">
      <path
        d={d}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface StationNodeData {
  station: StationType;
  label: string;
  state: StationVisualState;
  packages: PackagePosition[];
  isFocused: boolean;
  onSelectPackage: (packageId: string) => void;
  onHoverPackage: (packageId: string | null, anchor: { x: number; y: number } | null) => void;
}

// Package dots render as plain divs inside the node's own content, not
// as separate React Flow nodes — a station can hold dozens of packages
// at once, and giving each one RF's own node-store bookkeeping (meant
// for tens of draggable/connectable graph participants) would be pure
// overhead for content that never connects to an edge. Ordinary React
// event handlers work directly since drag/selection are disabled
// facility-wide.
function StationNode({ data }: { data: StationNodeData }) {
  const { station, label, state, packages, isFocused, onSelectPackage, onHoverPackage } = data;
  const cols = 4;
  const rowStep = 22;
  const dotAreaHeight = ZONE_HEIGHT - 86 - 16;
  const maxRows = Math.floor((dotAreaHeight - 12) / rowStep);
  const maxShown = cols * maxRows;
  const shown = packages.slice(0, maxShown);
  const overflow = packages.length - shown.length;

  return (
    <div
      className={`floor-plan-zone floor-plan-zone-${state}${isFocused ? " floor-plan-zone-focused" : ""}`}
      style={{ width: ZONE_WIDTH, height: ZONE_HEIGHT }}
    >
      <div className="zone-label">{label}</div>
      <div className="zone-rect">
        <div className="floor-plan-icon-wrap">
          <StationIcon station={station} state={state} />
        </div>
        <div className="zone-count">{packages.length}</div>
        <div className="zone-divider" />
        <div className="floor-plan-dot-area" style={{ height: dotAreaHeight }}>
          {shown.map((p, pi) => {
            const col = pi % cols;
            const row = Math.floor(pi / cols);
            const baseX = 20 + col * ((ZONE_WIDTH - 40) / (cols - 1));
            const baseY = 14 + row * rowStep;
            const dx = jitter(p.packageId, 4);
            const dy = jitter(p.packageId + "y", 4);
            const px = Math.min(ZONE_WIDTH - 11, Math.max(11, baseX + dx));
            const py = Math.min(dotAreaHeight - 6, Math.max(8, baseY + dy));
            const color = PACKAGE_COLORS[p.itemCategory] ?? PACKAGE_COLORS[0];
            return (
              <div
                key={p.packageId}
                className="floor-plan-dot"
                style={{ left: px, top: py, color }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectPackage(p.packageId);
                }}
                onMouseEnter={(e) => onHoverPackage(p.packageId, { x: e.clientX, y: e.clientY })}
                onMouseMove={(e) => onHoverPackage(p.packageId, { x: e.clientX, y: e.clientY })}
                onMouseLeave={() => onHoverPackage(null, null)}
              >
                <div className="floor-plan-dot-disc" />
                <PackageIconGlyph category={p.itemCategory} />
              </div>
            );
          })}
          {overflow > 0 && <div className="floor-plan-overflow">+{overflow} more</div>}
        </div>
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = { station: StationNode as unknown as NodeTypes["station"] };

interface FloorPlanProps {
  packagesByStation: Map<StationType, PackagePosition[]>;
  activeTravelers: Traveler[];
  stationState: Map<StationType, StationVisualState>;
  now: number;
  onSelectPackage: (packageId: string) => void;
  onHoverPackage: (packageId: string | null, anchor: { x: number; y: number } | null) => void;
  focusedStation: StationType | null;
  onOpenStation: (station: StationType) => void;
}

function FloorPlan({
  packagesByStation,
  activeTravelers,
  stationState,
  now,
  onSelectPackage,
  onHoverPackage,
  focusedStation,
  onOpenStation,
}: FloorPlanProps) {
  // Rebuilding this array is cheap, but hover state upstream (LiveView's
  // `hovered`) was getting lost mid-gesture when it was rebuilt every
  // 150ms tick from useFloorPlanTracking's `now` — each tick handed RF a
  // brand-new node/data identity even when nothing about a given
  // station's packages actually changed, and RF's own diffing/remount of
  // that node's content raced the mouseenter/mouseleave pair. Memoizing
  // on the actual inputs means a tick with no real station-data change
  // reuses the same node objects RF already has.
  const nodes: Node[] = useMemo(
    () =>
      STATIONS.map((station, i) => {
        const cx = zoneCenterX(i);
        return {
          id: String(station.type),
          type: "station",
          position: { x: cx - ZONE_WIDTH / 2, y: ZONE_TOP },
          // Explicit width/height so RF always knows this node's size
          // without needing to measure the rendered DOM — every live
          // position update gives this node's `data` a new object
          // identity (new `packages` array), and RF's own has-this-been-
          // measured tracking (NodeWrapper: `visibility: hasDimensions ?
          // 'visible' : 'hidden'`) was losing track of a prior
          // measurement on each such update, leaving nodes permanently
          // hidden once real traffic made updates continuous.
          width: ZONE_WIDTH,
          height: ZONE_HEIGHT,
          draggable: false,
          selectable: false,
          connectable: false,
          data: {
            station: station.type,
            label: station.label,
            state: stationState.get(station.type) ?? "normal",
            packages: packagesByStation.get(station.type) ?? [],
            isFocused: focusedStation === station.type,
            onSelectPackage,
            onHoverPackage,
          } satisfies StationNodeData,
        };
      }),
    [packagesByStation, stationState, focusedStation, onSelectPackage, onHoverPackage]
  );

  // RF's onNodeClick fires for the whole node regardless of a dot's own
  // onClick calling stopPropagation() — RF listens at the node wrapper
  // independently of where React's synthetic bubbling was stopped. Check
  // the actual click target instead so a dot click selects the package
  // without also opening its station's operations panel.
  const handleNodeClick: NodeMouseHandler = (event, node) => {
    if ((event.target as HTMLElement).closest(".floor-plan-dot")) return;
    const station = Number(node.id) as StationType;
    onOpenStation(station);
  };

  // fitView called once via onInit, not as a reactive `fitView` prop —
  // that prop re-triggers on every `nodes` change (i.e. every live
  // position update), which re-measures and re-hides nodes mid-
  // recalculation; with real traffic flowing that's constant, and
  // nodes never settle back to visible. The container is responsive
  // (percentage width up to max-width: 1180px per .facility-canvas), so
  // a single static zoom can't be hardcoded either — fitView once on
  // mount adapts to whatever the container's actual size is at load,
  // then stays fixed (pan/zoom are disabled below, so nothing further
  // ever changes the viewport after this).
  const handleInit = useCallback((instance: ReactFlowInstance) => {
    instance.fitView({ padding: 0 });
  }, []);

  return (
    <div className="floor-plan">
      <ReactFlow
        nodes={nodes}
        edges={[]}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onInit={handleInit}
        panOnDrag={false}
        panOnScroll={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <svg className="floor-plan-spine-svg" viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}>
          <line
            className="floor-plan-spine"
            x1={zoneCenterX(0)}
            y1={SPINE_Y}
            x2={zoneCenterX(STATIONS.length - 1)}
            y2={SPINE_Y}
          />
        </svg>
      </ReactFlow>
      <div className="floor-plan-traveler-overlay">
        {activeTravelers.map((t) => {
          const fromIdx = STATIONS.findIndex((s) => s.type === t.from);
          const toIdx = STATIONS.findIndex((s) => s.type === t.to);
          if (fromIdx === -1 || toIdx === -1) return null;
          const progress = Math.min(1, (now - t.startedAtMs) / TRAVEL_MS);
          const x = zoneCenterX(fromIdx) + (zoneCenterX(toIdx) - zoneCenterX(fromIdx)) * progress;
          const glyph = PACKAGE_GLYPHS[t.itemCategory] ?? PACKAGE_GLYPHS[0];
          const color = PACKAGE_COLORS[t.itemCategory] ?? PACKAGE_COLORS[0];
          return (
            <div
              key={t.packageId}
              className="floor-plan-traveler"
              style={{
                left: `${(x / CANVAS_WIDTH) * 100}%`,
                top: `${(SPINE_Y / CANVAS_HEIGHT) * 100}%`,
                color,
              }}
            >
              <svg viewBox="0 0 18 18" width="18" height="18">
                <circle cx="9" cy="9" r="9" className="floor-plan-traveler-disc" />
                <path
                  d={glyph}
                  transform="translate(2.6,2.6) scale(0.8)"
                  fill="none"
                  stroke="var(--panel)"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="floor-plan-traveler-glyph"
                />
              </svg>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default FloorPlan;
