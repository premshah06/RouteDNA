import type { PackagePosition } from "./useLiveFeed";
import { STATIONS, type StationType } from "./constants";
import StationIcon, { type StationVisualState } from "./StationIcon";
import { PACKAGE_COLORS, PACKAGE_GLYPHS } from "./packageGlyphs";
import type { Traveler } from "./useFloorPlanTracking";
import { TRAVEL_MS } from "./useFloorPlanTracking";
import "./FloorPlan.css";

// viewBox ratio matches the contained card in LiveView.css
// (.facility-canvas, aspect-ratio 1180/420) — a wide flow-path strip,
// not a full-bleed panel, so the map reads as one bounded diagram
// instead of stretching to fill whatever vertical space is available.
const CANVAS_WIDTH = 1180;
const CANVAS_HEIGHT = 420;
const ZONE_WIDTH = 138;
const ZONE_TOP = 60;
const ZONE_HEIGHT = 320;
const ZONE_GAP = (CANVAS_WIDTH - STATIONS.length * ZONE_WIDTH) / (STATIONS.length + 1);

// Inside each zone: the station name sits above the box (per the
// "name displayed on top" layout), the icon + count sit in a compact
// header band inside the box, and the package-dot floor fills the
// rest. The conveyor spine runs through the dot area's vertical
// center so travelers appear to ride the belt between zone floors.
const LABEL_Y = ZONE_TOP - 14;
const HEADER_HEIGHT = 86;
const DOT_AREA_TOP = ZONE_TOP + HEADER_HEIGHT;
const DOT_AREA_HEIGHT = ZONE_HEIGHT - HEADER_HEIGHT - 16;
const SPINE_Y = DOT_AREA_TOP + DOT_AREA_HEIGHT / 2;

function zoneCenterX(index: number): number {
  return ZONE_GAP + index * (ZONE_WIDTH + ZONE_GAP) + ZONE_WIDTH / 2;
}

// Deterministic pseudo-random offset so a station's packages spread out
// across its zone instead of stacking on one pixel — a layout position
// for legibility, not a claim about real physical placement on the belt
// (the feed has no sub-station coordinate data, same honesty tradeoff
// as the travel animation itself).
function jitter(packageId: string, spread: number): number {
  let hash = 0;
  for (let i = 0; i < packageId.length; i++) {
    hash = (hash * 31 + packageId.charCodeAt(i)) | 0;
  }
  return ((Math.abs(hash) % 1000) / 1000 - 0.5) * spread;
}

interface FloorPlanProps {
  packagesByStation: Map<StationType, PackagePosition[]>;
  activeTravelers: Traveler[];
  stationState: Map<StationType, StationVisualState>;
  now: number;
  onSelectPackage: (packageId: string) => void;
  onHoverPackage: (packageId: string | null, anchor: { x: number; y: number } | null) => void;
  focusedStation: StationType | null;
  onFocusStation: (station: StationType) => void;
}

function FloorPlan({
  packagesByStation,
  activeTravelers,
  stationState,
  now,
  onSelectPackage,
  onHoverPackage,
  focusedStation,
  onFocusStation,
}: FloorPlanProps) {
  return (
    <div className="floor-plan">
      {/* Everything lives inside this one SVG (station icons included,
          via foreignObject) so zones, headers, dots, and travelers all
          share a single coordinate system — an HTML overlay positioned
          by container percentages drifts against the SVG whenever
          preserveAspectRatio letterboxes it. */}
      <svg
        className="floor-plan-svg"
        viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* One straight conveyor spine through every zone in sequence —
            matches the facility's real linear routing chain. */}
        <line
          className="floor-plan-spine"
          x1={zoneCenterX(0)}
          y1={SPINE_Y}
          x2={zoneCenterX(STATIONS.length - 1)}
          y2={SPINE_Y}
        />

        {STATIONS.map((station, i) => {
          const state = stationState.get(station.type) ?? "normal";
          const count = packagesByStation.get(station.type)?.length ?? 0;
          const cx = zoneCenterX(i);
          const x = cx - ZONE_WIDTH / 2;
          const isFocused = focusedStation === station.type;
          return (
            <g
              key={station.type}
              className={`floor-plan-zone floor-plan-zone-${state}${isFocused ? " floor-plan-zone-focused" : ""}`}
              onClick={() => onFocusStation(station.type)}
            >
              {/* Station name above the box. */}
              <text className="zone-label" x={cx} y={LABEL_Y} textAnchor="middle">
                {station.label}
              </text>
              <rect className="zone-rect" x={x} y={ZONE_TOP} width={ZONE_WIDTH} height={ZONE_HEIGHT} rx={10} />
              <line
                className="zone-divider"
                x1={x + 10}
                x2={x + ZONE_WIDTH - 10}
                y1={DOT_AREA_TOP - 2}
                y2={DOT_AREA_TOP - 2}
              />
              <foreignObject x={cx - 24} y={ZONE_TOP + 6} width={48} height={48}>
                <div className="floor-plan-icon-wrap">
                  <StationIcon station={station.type} state={state} />
                </div>
              </foreignObject>
              <text className="zone-count" x={cx} y={ZONE_TOP + 68} textAnchor="middle">
                {count}
              </text>
            </g>
          );
        })}

        {activeTravelers.map((t) => {
          const fromIdx = STATIONS.findIndex((s) => s.type === t.from);
          const toIdx = STATIONS.findIndex((s) => s.type === t.to);
          if (fromIdx === -1 || toIdx === -1) return null;
          const progress = Math.min(1, (now - t.startedAtMs) / TRAVEL_MS);
          const x = zoneCenterX(fromIdx) + (zoneCenterX(toIdx) - zoneCenterX(fromIdx)) * progress;
          const glyph = PACKAGE_GLYPHS[t.itemCategory] ?? PACKAGE_GLYPHS[0];
          const color = PACKAGE_COLORS[t.itemCategory] ?? PACKAGE_COLORS[0];
          return (
            <g
              key={t.packageId}
              className="floor-plan-traveler"
              transform={`translate(${x},${SPINE_Y})`}
              style={{ color }}
            >
              <circle r={9} className="floor-plan-traveler-disc" />
              <path
                d={glyph}
                transform="translate(-6.4,-6.4) scale(0.8)"
                fill="none"
                stroke="var(--panel)"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="floor-plan-traveler-glyph"
              />
            </g>
          );
        })}

        {STATIONS.map((station, i) => {
          const packages = packagesByStation.get(station.type) ?? [];
          const cx = zoneCenterX(i);
          const zoneX = cx - ZONE_WIDTH / 2;
          // Grid of dot slots on the zone's floor area — a
          // representative sample; beyond that, an overflow count.
          const cols = 4;
          const rowStep = 22;
          const maxRows = Math.floor((DOT_AREA_HEIGHT - 12) / rowStep);
          const maxShown = cols * maxRows;
          const shown = packages.slice(0, maxShown);
          const overflow = packages.length - shown.length;
          return (
            <g key={`dots-${station.type}`}>
              {shown.map((p, pi) => {
                const col = pi % cols;
                const row = Math.floor(pi / cols);
                const baseX = zoneX + 20 + col * ((ZONE_WIDTH - 40) / (cols - 1));
                const baseY = DOT_AREA_TOP + 14 + row * rowStep;
                const dx = jitter(p.packageId, 4);
                const dy = jitter(p.packageId + "y", 4);
                const px = Math.min(zoneX + ZONE_WIDTH - 11, Math.max(zoneX + 11, baseX + dx));
                const py = Math.min(DOT_AREA_TOP + DOT_AREA_HEIGHT - 6, Math.max(DOT_AREA_TOP + 8, baseY + dy));
                const color = PACKAGE_COLORS[p.itemCategory] ?? PACKAGE_COLORS[0];
                return (
                  <g
                    key={p.packageId}
                    className="floor-plan-dot"
                    transform={`translate(${px},${py})`}
                    style={{ color }}
                    onClick={() => onSelectPackage(p.packageId)}
                    onMouseEnter={(e) => onHoverPackage(p.packageId, { x: e.clientX, y: e.clientY })}
                    onMouseMove={(e) => onHoverPackage(p.packageId, { x: e.clientX, y: e.clientY })}
                    onMouseLeave={() => onHoverPackage(null, null)}
                  >
                    <circle r={6.5} className="floor-plan-dot-disc" />
                    <PackageIconGlyph category={p.itemCategory} />
                  </g>
                );
              })}
              {overflow > 0 && (
                <text className="floor-plan-overflow" x={cx} y={ZONE_TOP + ZONE_HEIGHT - 8} textAnchor="middle">
                  +{overflow} more
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// A bare glyph path (no wrapping <svg>) sized for the small dot radius
// used on the floor plan — PackageIcon renders its own <svg> root,
// which can't nest inside this component's parent <svg>, so the floor
// plan draws the glyph path directly.
function PackageIconGlyph({ category }: { category: number }) {
  const d = PACKAGE_GLYPHS[category] ?? PACKAGE_GLYPHS[0];
  return (
    <path
      d={d}
      transform="translate(-5.2,-5.2) scale(0.65)"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="floor-plan-dot-glyph"
    />
  );
}

export default FloorPlan;
