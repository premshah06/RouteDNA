import type { StationType } from "./constants";
import "./StationIcon.css";

export type StationVisualState = "normal" | "warning" | "critical";

interface StationIconProps {
  station: StationType;
  state: StationVisualState;
}

// One illustrated icon per station type, isometric style matching the
// rest of the dashboard's dark theme + categorical palette. `state`
// drives the glow color and animation speed so the same icon reads as
// "flowing normally" vs "needs attention" without changing shape —
// see LiveView.tsx for how state is derived from real alert data.
function StationIcon({ station, state }: StationIconProps) {
  const props = { className: `station-icon station-icon-${state}` };
  switch (station) {
    case 1:
      return <IntakeIcon {...props} />;
    case 2:
      return <SortIcon {...props} direction="left" />;
    case 3:
      return <SortIcon {...props} direction="right" />;
    case 4:
      return <DispatchIcon {...props} />;
    case 5:
      return <InductionIcon {...props} />;
    case 6:
      return <QcCheckIcon {...props} />;
    case 7:
      return <StagingIcon {...props} />;
    default:
      return null;
  }
}

function IntakeIcon({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 160 160" width="88" height="88">
      <ellipse className="icon-glow" cx="80" cy="118" rx="58" ry="14" />
      <polygon className="icon-belt-top intake-fill" points="24,96 80,66 136,96 80,126" />
      <g className="icon-chevrons" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <path d="M46,90 L58,84" />
        <path d="M68,84 L80,78" />
        <path d="M90,84 L102,90" />
        <path d="M112,90 L124,96" />
      </g>
      <polygon className="icon-belt-front intake-front" points="24,96 24,104 80,134 80,126" />
      <polygon className="icon-belt-side intake-side" points="136,96 136,104 80,134 80,126" />
      <polygon className="icon-belt-edge" points="24,96 80,66 136,96 80,126" />
      <g className="icon-rollers">
        <ellipse cx="40" cy="92" rx="4.5" ry="8" />
        <ellipse cx="80" cy="112" rx="4.5" ry="8" />
        <ellipse cx="120" cy="92" rx="4.5" ry="8" />
      </g>
      <path className="icon-arch" d="M56,64 L56,30 Q56,18 68,18 L92,18 Q104,18 104,30 L104,64" />
      <line className="icon-scan-beam" x1="60" y1="46" x2="100" y2="46" />
      <g transform="translate(80,78)">
        <polygon className="icon-package-top" points="-13,-6 0,-13 13,-6 0,1" />
        <polygon className="icon-package-front" points="-13,-6 -13,5 0,12 0,1" />
        <polygon className="icon-package-side" points="13,-6 13,5 0,12 0,1" />
      </g>
    </svg>
  );
}

function SortIcon({ className, direction }: { className: string; direction: "left" | "right" }) {
  const armRotate = direction === "left" ? -18 : 18;
  return (
    <svg className={className} viewBox="0 0 160 160" width="88" height="88">
      <ellipse className="icon-glow" cx="80" cy="122" rx="58" ry="13" />
      {/* Single belt bed (same silhouette family as Intake/Dispatch, so
          all four icons sit on the belt curves the same way) with a
          fork painted on its surface — reads as "one line splits into
          two" without needing separate chute geometry hanging below
          the bed, which is what made this icon crowd/clip at 88px. */}
      <polygon className={`icon-belt-top sort-fill-${direction}`} points="24,90 80,60 136,90 80,120" />
      <polygon className={`icon-belt-front sort-front-${direction}`} points="24,90 24,98 80,128 80,120" />
      <polygon className={`icon-belt-side sort-side-${direction}`} points="136,90 136,98 80,128 80,120" />
      <polygon className="icon-belt-edge" points="24,90 80,60 136,90 80,120" />
      <path
        className={`sort-chute-${direction}`}
        d="M80,72 L80,84 M80,84 L58,96 M80,84 L102,96"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle className="icon-diverter-housing" cx="80" cy="60" r="13" />
      <g
        className="icon-diverter-arm"
        style={{ transformOrigin: "80px 60px", ["--arm-rotate" as string]: `${armRotate}deg` }}
      >
        <path d="M80,52 L80,68" strokeWidth="3" strokeLinecap="round" />
        <path d="M80,52 L76,57 M80,52 L84,57" strokeWidth="2.5" strokeLinecap="round" />
      </g>
    </svg>
  );
}

function DispatchIcon({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 160 160" width="88" height="88">
      <ellipse className="icon-glow" cx="80" cy="128" rx="58" ry="12" />
      <polygon className="icon-belt-top dispatch-fill" points="24,92 80,62 136,92 80,122" />
      <polygon className="icon-belt-front dispatch-front" points="24,92 24,100 80,130 80,122" />
      <polygon className="icon-belt-side dispatch-side" points="136,92 136,100 80,130 80,122" />
      <polygon className="icon-belt-edge" points="24,92 80,62 136,92 80,122" />
      <g transform="translate(80,90)" className="icon-truck">
        <polygon points="-22,-4 -4,-14 14,-14 22,-4 22,10 -22,10" />
        <polygon className="icon-truck-cab" points="-4,-14 14,-14 14,-2 -4,-2" />
        <circle className="icon-truck-wheel" cx="-10" cy="12" r="4.5" />
        <circle className="icon-truck-wheel" cx="12" cy="12" r="4.5" />
      </g>
      <path className="icon-dispatch-arrow" d="M80,44 L80,16 M70,26 L80,14 L90,26" fill="none" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function InductionIcon({ className }: { className: string }) {
  // Two intake lanes merging onto one belt — the station right after
  // Intake that funnels packages onto the single sequential line the
  // rest of the facility (Sort A -> ... -> Dispatch) expects.
  return (
    <svg className={className} viewBox="0 0 160 160" width="88" height="88">
      <ellipse className="icon-glow" cx="80" cy="122" rx="58" ry="13" />
      <polygon className="icon-belt-top induction-fill" points="24,90 80,60 136,90 80,120" />
      <polygon className="icon-belt-front induction-front" points="24,90 24,98 80,128 80,120" />
      <polygon className="icon-belt-side induction-side" points="136,90 136,98 80,128 80,120" />
      <polygon className="icon-belt-edge" points="24,90 80,60 136,90 80,120" />
      <path
        className="induction-merge"
        d="M52,78 L80,92 M108,78 L80,92 M80,92 L80,104"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function QcCheckIcon({ className }: { className: string }) {
  // Inspection gantry with a magnifier/checkmark badge — the station
  // that verifies a package (post-sort) before it's cleared to stage.
  return (
    <svg className={className} viewBox="0 0 160 160" width="88" height="88">
      <ellipse className="icon-glow" cx="80" cy="122" rx="58" ry="13" />
      <polygon className="icon-belt-top qc-fill" points="24,90 80,60 136,90 80,120" />
      <polygon className="icon-belt-front qc-front" points="24,90 24,98 80,128 80,120" />
      <polygon className="icon-belt-side qc-side" points="136,90 136,98 80,128 80,120" />
      <polygon className="icon-belt-edge" points="24,90 80,60 136,90 80,120" />
      <path className="icon-arch qc-gantry" d="M52,88 L52,54 Q52,44 62,44 L98,44 Q108,44 108,54 L108,88" />
      <circle className="qc-badge" cx="80" cy="70" r="11" />
      <path className="qc-check" d="M74,70 L78,75 L87,64" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function StagingIcon({ className }: { className: string }) {
  // Stacked crates waiting on the belt — the holding area right
  // before Dispatch, distinct from Dispatch's outbound-truck imagery.
  return (
    <svg className={className} viewBox="0 0 160 160" width="88" height="88">
      <ellipse className="icon-glow" cx="80" cy="128" rx="58" ry="12" />
      <polygon className="icon-belt-top staging-fill" points="24,92 80,62 136,92 80,122" />
      <polygon className="icon-belt-front staging-front" points="24,92 24,100 80,130 80,122" />
      <polygon className="icon-belt-side staging-side" points="136,92 136,100 80,130 80,122" />
      <polygon className="icon-belt-edge" points="24,92 80,62 136,92 80,122" />
      <g transform="translate(80,84)">
        <polygon className="staging-crate staging-crate-back" points="-10,-16 0,-21 10,-16 0,-11" />
        <polygon className="staging-crate staging-crate-back-side" points="-10,-16 -10,-6 0,-1 0,-11" />
        <polygon className="staging-crate staging-crate-top" points="-11,-2 0,-8 11,-2 0,4" />
        <polygon className="staging-crate staging-crate-front" points="-11,-2 -11,9 0,15 0,4" />
        <polygon className="staging-crate staging-crate-side" points="11,-2 11,9 0,15 0,4" />
      </g>
    </svg>
  );
}

export default StationIcon;
