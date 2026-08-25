import { useEffect, useMemo, useRef, useState } from "react";
import { useFacilityStats, type TrendsRange } from "./useFacilityStats";
import { ALERT_TYPE_LABEL, ITEM_CATEGORY_LABEL, STATION_LABEL, type StationType, timeAgo } from "./constants";
import "./TrendsView.css";

// Dark-mode categorical steps from this app's design system (see
// dataviz skill's references/palette.md) — first N slots in fixed
// order, never reassigned per-filter.
const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"];

function BarChart({
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

function LineChart({ points, emptyHint }: LineChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (points.length === 0) return <div className="chart-empty">{emptyHint ?? "No data yet"}</div>;
  // A single point has nothing to connect — a line/area chart of one
  // dot reads as a rendering bug, not "one day of data." Show it as a
  // labeled figure instead, same idea as this skill's stat-tile contract.
  if (points.length === 1) {
    return (
      <div className="line-chart-single">
        <span className="line-chart-single-value">{points[0].value.toLocaleString()}</span>
        <span className="line-chart-single-label">{points[0].label}</span>
      </div>
    );
  }
  const width = 600;
  const height = 160;
  const padding = 8;
  const max = Math.max(...points.map((p) => p.value), 1);
  const stepX = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;

  const coords = points.map((p, i) => ({
    x: padding + i * stepX,
    y: height - padding - (p.value / max) * (height - padding * 2),
  }));

  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1].x},${height - padding} L${coords[0].x},${height - padding} Z`;

  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * width;
    // Crosshair snaps to the nearest data position, per the dataviz
    // skill's interaction rules — readers aim at a date, not a pixel.
    let nearest = 0;
    let nearestDist = Infinity;
    coords.forEach((c, i) => {
      const dist = Math.abs(c.x - relX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIdx(nearest);
  };

  const hovered = hoverIdx !== null ? { point: points[hoverIdx], coord: coords[hoverIdx] } : null;

  return (
    <div className="line-chart-wrap">
      <svg
        className="line-chart"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        <path d={areaPath} fill={SERIES[0]} opacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke={SERIES[0]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {coords.map((c, i) => (
          <circle key={i} cx={c.x} cy={c.y} r={4} fill={SERIES[0]} stroke="var(--panel)" strokeWidth={2} />
        ))}
        {hovered && (
          <line
            className="line-chart-crosshair"
            x1={hovered.coord.x}
            x2={hovered.coord.x}
            y1={0}
            y2={height}
          />
        )}
        {hovered && (
          <circle cx={hovered.coord.x} cy={hovered.coord.y} r={6} className="line-chart-hover-dot" />
        )}
      </svg>
      {hovered && (
        <div
          className="line-chart-tooltip"
          style={{ left: `${(hovered.coord.x / width) * 100}%` }}
        >
          <div className="line-chart-tooltip-value">{hovered.point.value.toLocaleString()}</div>
          <div className="line-chart-tooltip-label">{hovered.point.label}</div>
        </div>
      )}
    </div>
  );
}

function Histogram({ data, valueFmt }: { data: { label: string; value: number }[]; valueFmt: (v: number) => string }) {
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

const RANGE_TABS: { key: TrendsRange; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "month", label: "This month" },
];

type SortKey = "time" | "station" | "issue";

interface TrendsViewProps {
  onOpenJourney: (packageId: string) => void;
  focusedStation: StationType | null;
  onFocusStation: (station: StationType) => void;
  onClearFocus: () => void;
}

// Reverse lookup: STATION_LABEL by enum value; find the enum value for
// a given label so a click on a station's name/bar can resolve back to
// a StationType to hand up to App.tsx.
function stationTypeForLabel(label: string): StationType | undefined {
  const entry = Object.entries(STATION_LABEL).find(([, l]) => l === label);
  return entry ? (Number(entry[0]) as StationType) : undefined;
}

function TrendsView({ onOpenJourney, focusedStation, onFocusStation, onClearFocus }: TrendsViewProps) {
  const [range, setRange] = useState<TrendsRange>("today");
  const { stats, status } = useFacilityStats(range);
  const [filterText, setFilterText] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("time");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [pulseCard, setPulseCard] = useState(false);
  const damageCardRef = useRef<HTMLElement>(null);

  // Arriving here with a focused station (a click from the Live floor
  // plan) pre-fills the flagged-parcels filter to that station and
  // draws attention to the damage-by-station card — the two places on
  // this tab that are actually station-scoped.
  useEffect(() => {
    if (!focusedStation) return;
    const label = STATION_LABEL[focusedStation];
    if (label) setFilterText(label);
    damageCardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    setPulseCard(true);
    const timer = setTimeout(() => setPulseCard(false), 1500);
    return () => clearTimeout(timer);
  }, [focusedStation]);

  const flaggedRows = useMemo(() => {
    if (!stats) return [];
    const needle = filterText.trim().toLowerCase();
    let rows = stats.recentFlagged;
    if (needle) {
      rows = rows.filter((f) => {
        const issue = (ALERT_TYPE_LABEL[f.alertType] ?? "").toLowerCase();
        const station = (STATION_LABEL[f.station] ?? "").toLowerCase();
        return (
          f.packageId.toLowerCase().includes(needle) ||
          issue.includes(needle) ||
          station.includes(needle)
        );
      });
    }
    const sorted = [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "time") cmp = a.detectedAtMs - b.detectedAtMs;
      else if (sortKey === "station") cmp = (STATION_LABEL[a.station] ?? "").localeCompare(STATION_LABEL[b.station] ?? "");
      else cmp = (ALERT_TYPE_LABEL[a.alertType] ?? "").localeCompare(ALERT_TYPE_LABEL[b.alertType] ?? "");
      return cmp * sortDir;
    });
    return sorted;
  }, [stats, filterText, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      setSortDir(-1);
    }
  }

  function sortIndicator(key: SortKey) {
    if (sortKey !== key) return "";
    return sortDir === 1 ? " ▲" : " ▼";
  }

  return (
    <main className="trends">
      <div className="trends-tabs">
        {RANGE_TABS.map((tab) => (
          <button
            key={tab.key}
            className={`trends-tab${range === tab.key ? " active" : ""}`}
            onClick={() => {
              setRange(tab.key);
              if (focusedStation) onClearFocus();
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {status === "loading" && !stats && <div className="chart-empty">Loading trends…</div>}
      {status === "error" && <div className="chart-empty error">Couldn't load facility stats.</div>}

      {stats && (
        <div className="trends-grid">
          <section className="trends-card trends-card-wide">
            <h3>Throughput over time</h3>
            <LineChart
              points={stats.throughputSeries.map((p) => ({
                label: new Date(p.bucketMs).toLocaleDateString(),
                value: p.count,
              }))}
              emptyHint="No batch report for this range yet — the daily throughput job hasn't run."
            />
          </section>

          <section
            className={`trends-card${pulseCard ? " trends-card-pulse" : ""}`}
            ref={damageCardRef}
          >
            <h3>Damage rate by station</h3>
            <BarChart
              data={stats.damageByStation.map((d) => ({
                label: STATION_LABEL[d.station] ?? "Unknown",
                value: d.damageRate,
              }))}
              valueFmt={(v) => `${(v * 100).toFixed(1)}%`}
              emptyHint="No batch report for this range yet."
              onBarClick={(label) => {
                const station = stationTypeForLabel(label);
                if (station !== undefined) onFocusStation(station);
              }}
            />
          </section>

          <section className="trends-card">
            <h3>Damage rate by item category</h3>
            <BarChart
              data={stats.damageByCategory
                .slice()
                .sort((a, b) => b.damageRate - a.damageRate)
                .map((d) => ({
                  label: ITEM_CATEGORY_LABEL[d.itemCategory] ?? "Unknown",
                  value: d.damageRate,
                }))}
              valueFmt={(v) => `${(v * 100).toFixed(1)}%`}
              emptyHint="No batch report for this range yet."
            />
          </section>

          <section className="trends-card">
            <h3>Alert breakdown</h3>
            <BarChart
              data={stats.alertBreakdown.map((a) => ({
                label: ALERT_TYPE_LABEL[a.alertType] ?? "Unknown",
                value: a.count,
              }))}
              valueFmt={(v) => v.toLocaleString()}
            />
          </section>

          <section className="trends-card trends-card-wide">
            <h3>Busiest hours</h3>
            <Histogram
              data={Array.from({ length: 24 }, (_, hour) => {
                const found = stats.busiestHours.find((h) => h.hour === hour);
                return { label: `${hour}`, value: found?.count ?? 0 };
              })}
              valueFmt={(v) => v.toLocaleString()}
            />
          </section>

          <section className="trends-card trends-card-wide">
            <div className="trends-card-header-row">
              <h3>Recent flagged parcels</h3>
              <input
                className="flagged-filter"
                type="text"
                placeholder="Filter by parcel, issue, or station…"
                value={filterText}
                onChange={(e) => {
                  setFilterText(e.target.value);
                  if (focusedStation) onClearFocus();
                }}
              />
            </div>
            <div className="flagged-table-scroll">
            <table className="flagged-table">
              <thead>
                <tr>
                  <th>Parcel</th>
                  <th className="sortable" onClick={() => toggleSort("issue")}>
                    Issue{sortIndicator("issue")}
                  </th>
                  <th className="sortable" onClick={() => toggleSort("station")}>
                    Station{sortIndicator("station")}
                  </th>
                  <th className="sortable" onClick={() => toggleSort("time")}>
                    Time{sortIndicator("time")}
                  </th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {flaggedRows.map((f) => (
                  <tr key={`${f.packageId}-${f.detectedAtMs}`}>
                    <td>{f.packageId.slice(0, 8)}</td>
                    <td>{ALERT_TYPE_LABEL[f.alertType] ?? "Alert"}</td>
                    <td className="flagged-station-cell" onClick={() => onFocusStation(f.station)}>
                      {STATION_LABEL[f.station] ?? "—"}
                    </td>
                    <td>{timeAgo(f.detectedAtMs)}</td>
                    <td>
                      <button className="flagged-open" onClick={() => onOpenJourney(f.packageId)}>
                        Open →
                      </button>
                    </td>
                  </tr>
                ))}
                {flaggedRows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="chart-empty">
                      {filterText ? "No parcels match this filter." : "No flagged parcels in this range."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default TrendsView;
