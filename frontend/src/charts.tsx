import { useState } from "react";

// Dark-mode categorical steps from this app's design system (see
// dataviz skill's references/palette.md) — first N slots in fixed
// order, never reassigned per-filter.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"];

export function BarChart({
  data,
  valueFmt,
  emptyHint,
  onBarClick,
}: {
  data: { label: string; value: number }[];
  valueFmt: (v: number) => string;
  emptyHint?: string;
  onBarClick?: (label: string) => void;
}) {
  const max = Math.max(...data.map((d) => d.value), 0.0001);
  return (
    <div className="bar-chart">
      {data.map((d, i) => (
        <div
          key={d.label}
          className={`bar-row${onBarClick ? " bar-row-clickable" : ""}`}
          onClick={onBarClick ? () => onBarClick(d.label) : undefined}
        >
          <div className="bar-label">{d.label}</div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{ width: `${(d.value / max) * 100}%`, background: SERIES[i % SERIES.length] }}
            />
          </div>
          <div className="bar-value">{valueFmt(d.value)}</div>
        </div>
      ))}
      {data.length === 0 && <div className="chart-empty">{emptyHint ?? "No data yet"}</div>}
    </div>
  );
}

interface LineChartProps {
  points: { label: string; value: number }[];
  emptyHint?: string;
}

export function LineChart({ points, emptyHint }: LineChartProps) {
  if (points.length === 0) return <div className="chart-empty">{emptyHint ?? "No data yet"}</div>;
  return (
    <MultiLineChart
      series={[{ name: "value", color: SERIES[0], points }]}
      emptyHint={emptyHint}
      showArea
    />
  );
}

interface MultiSeriesDef {
  name: string;
  color: string;
  points: { label: string; value: number }[];
}

interface MultiLineChartProps {
  series: MultiSeriesDef[];
  emptyHint?: string;
  showArea?: boolean;
  // Compact mode drops the legend/tooltip/axis chrome for small
  // repeated charts (e.g. one per station) where a full interactive
  // chart per instance would be visual noise — used by QueueDepthPanel.
  compact?: boolean;
  height?: number;
}

// Shared by the single-series throughput chart (via LineChart above),
// the multi-series alert-trend chart, and (in compact mode) the
// per-station queue-depth sparklines. Per the dataviz skill's
// interaction rules: the crosshair snaps to the nearest X, and one
// tooltip lists every series at that X rather than requiring the
// pointer to land on a specific line.
export function MultiLineChart({ series, emptyHint, showArea, compact, height = 160 }: MultiLineChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const pointCount = series[0]?.points.length ?? 0;
  if (pointCount === 0) return <div className="chart-empty">{emptyHint ?? "No data yet"}</div>;
  // A single point has nothing to connect — a line/area chart of one
  // dot reads as a rendering bug, not "one day of data." Show it as a
  // labeled figure instead, same idea as this skill's stat-tile contract.
  if (pointCount === 1 && !compact) {
    return (
      <div className="line-chart-single">
        {series.map((s) => (
          <div key={s.name} className="line-chart-single-series">
            <span className="line-chart-single-value" style={{ color: s.color }}>
              {s.points[0].value.toLocaleString()}
            </span>
            <span className="line-chart-single-label">{s.name}</span>
          </div>
        ))}
      </div>
    );
  }

  const width = 600;
  const padding = 8;
  const max = Math.max(...series.flatMap((s) => s.points.map((p) => p.value)), 1);
  const stepX = pointCount > 1 ? (width - padding * 2) / (pointCount - 1) : 0;

  const seriesCoords = series.map((s) => ({
    ...s,
    coords: s.points.map((p, i) => ({
      x: padding + i * stepX,
      y: height - padding - (p.value / max) * (height - padding * 2),
    })),
  }));

  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * width;
    let nearest = 0;
    let nearestDist = Infinity;
    seriesCoords[0].coords.forEach((c, i) => {
      const dist = Math.abs(c.x - relX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIdx(nearest);
  };

  const hoverX = hoverIdx !== null ? seriesCoords[0].coords[hoverIdx].x : null;

  return (
    <div className="line-chart-wrap">
      {!compact && series.length > 1 && (
        <div className="line-chart-legend">
          {series.map((s) => (
            <span key={s.name} className="line-chart-legend-item">
              <span className="line-chart-legend-swatch" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <svg
        className={`line-chart${compact ? " line-chart-compact" : ""}`}
        style={{ height }}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {seriesCoords.map((s) => {
          const linePath = s.coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");
          const areaPath = showArea
            ? `${linePath} L${s.coords[s.coords.length - 1].x},${height - padding} L${s.coords[0].x},${height - padding} Z`
            : null;
          return (
            <g key={s.name}>
              {areaPath && <path d={areaPath} fill={s.color} opacity={0.1} stroke="none" />}
              <path d={linePath} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              {!compact &&
                s.coords.map((c, i) => (
                  <circle key={i} cx={c.x} cy={c.y} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={2} />
                ))}
            </g>
          );
        })}
        {hoverX !== null && (
          <line className="line-chart-crosshair" x1={hoverX} x2={hoverX} y1={0} y2={height} />
        )}
        {hoverX !== null &&
          seriesCoords.map((s) => (
            <circle
              key={s.name}
              cx={s.coords[hoverIdx!].x}
              cy={s.coords[hoverIdx!].y}
              r={compact ? 4 : 6}
              className="line-chart-hover-dot"
              stroke={s.color}
            />
          ))}
      </svg>
      {hoverIdx !== null && (
        <div className="line-chart-tooltip" style={{ left: `${(hoverX! / width) * 100}%` }}>
          <div className="line-chart-tooltip-label">{series[0].points[hoverIdx].label}</div>
          {seriesCoords.map((s) => (
            <div key={s.name} className="line-chart-tooltip-row">
              <span className="line-chart-tooltip-key" style={{ background: s.color }} />
              <span className="line-chart-tooltip-series-value">{s.points[hoverIdx].value.toLocaleString()}</span>
              {series.length > 1 && <span className="line-chart-tooltip-series-name">{s.name}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Histogram({ data, valueFmt }: { data: { label: string; value: number }[]; valueFmt: (v: number) => string }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="histogram">
      {data.map((d, i) => (
        <div
          key={d.label}
          className="histogram-col"
          onMouseEnter={() => setHoverIdx(i)}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {hoverIdx === i && (
            <div className="histogram-tooltip">
              {valueFmt(d.value)} · {d.label}
            </div>
          )}
          <div className="histogram-bar-track">
            <div
              className={`histogram-bar${hoverIdx === i ? " histogram-bar-hover" : ""}${d.value === 0 ? " histogram-bar-zero" : ""}`}
              // A non-zero hour with a tiny share of the max still gets
              // a visible sliver (min 3%) rather than rounding to
              // invisible next to one dominant hour — zero stays truly
              // flat so "no traffic" and "a little traffic" stay
              // visually distinct.
              style={{ height: d.value === 0 ? "2px" : `${Math.max(3, (d.value / max) * 100)}%` }}
            />
          </div>
          <div className="histogram-label">{d.label}</div>
        </div>
      ))}
      {data.every((d) => d.value === 0) && <div className="chart-empty histogram-empty">No data yet</div>}
    </div>
  );
}
