import { useEffect, useMemo, useRef, useState } from "react";
import { useFacilityStats, type TrendsRange, type TrendsRangePreset, type FlaggedParcel } from "./useFacilityStats";
import { ALERT_TYPE_LABEL, ITEM_CATEGORY_LABEL, STATION_LABEL, type StationType, timeAgo } from "./constants";
import { Button } from "@/components/ui/button";
import { BarChart, LineChart, MultiLineChart, Histogram, SERIES } from "./charts";
import "./TrendsView.css";

const RANGE_TABS: { key: TrendsRangePreset; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "month", label: "This month" },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

type SortKey = "time" | "station" | "issue";

interface TrendsViewProps {
  onOpenJourney: (parcel: FlaggedParcel) => void;
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
  const [isCustom, setIsCustom] = useState(false);
  const [customStart, setCustomStart] = useState(todayIso());
  const [customEnd, setCustomEnd] = useState(todayIso());
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

  function exportCsv() {
    // Exports exactly what's on screen — the currently filtered/sorted
    // rows, same array the table renders from — not a fresh unfiltered
    // fetch, so the file matches what the user was just looking at.
    const header = ["Parcel ID", "Issue", "Station", "Detected At"];
    const csvEscape = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const lines = [
      header.map(csvEscape).join(","),
      ...flaggedRows.map((f) =>
        [
          f.packageId,
          ALERT_TYPE_LABEL[f.alertType] ?? "Alert",
          STATION_LABEL[f.station] ?? "",
          new Date(f.detectedAtMs).toISOString(),
        ]
          .map(csvEscape)
          .join(",")
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `flagged-parcels-${todayIso()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

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
            className={`trends-tab${!isCustom && range === tab.key ? " active" : ""}`}
            onClick={() => {
              setIsCustom(false);
              setRange(tab.key);
              if (focusedStation) onClearFocus();
            }}
          >
            {tab.label}
          </button>
        ))}
        <button
          className={`trends-tab${isCustom ? " active" : ""}`}
          onClick={() => {
            setIsCustom(true);
            setRange({ start: customStart, end: customEnd });
            if (focusedStation) onClearFocus();
          }}
        >
          Custom
        </button>
        {isCustom && (
          <div className="trends-date-range">
            <input
              type="date"
              className="trends-date-input"
              value={customStart}
              max={customEnd}
              onChange={(e) => {
                setCustomStart(e.target.value);
                setRange({ start: e.target.value, end: customEnd });
              }}
            />
            <span className="trends-date-sep">to</span>
            <input
              type="date"
              className="trends-date-input"
              value={customEnd}
              min={customStart}
              max={todayIso()}
              onChange={(e) => {
                setCustomEnd(e.target.value);
                setRange({ start: customStart, end: e.target.value });
              }}
            />
          </div>
        )}
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

          <section className="trends-card trends-card-wide">
            <h3>Alerts over time</h3>
            <MultiLineChart
              series={(() => {
                const byType = new Map<number, { bucketMs: number; count: number }[]>();
                for (const t of stats.alertTrend) {
                  if (!byType.has(t.alertType)) byType.set(t.alertType, []);
                  byType.get(t.alertType)!.push({ bucketMs: t.bucketMs, count: t.count });
                }
                const buckets = Array.from(new Set(stats.alertTrend.map((t) => t.bucketMs))).sort((a, b) => a - b);
                return Array.from(byType.entries()).map(([alertType, points], i) => {
                  const byBucket = new Map(points.map((p) => [p.bucketMs, p.count]));
                  return {
                    name: ALERT_TYPE_LABEL[alertType] ?? "Unknown",
                    color: SERIES[i % SERIES.length],
                    points: buckets.map((b) => ({
                      label: new Date(b).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" }),
                      value: byBucket.get(b) ?? 0,
                    })),
                  };
                });
              })()}
              emptyHint="No alerts in this range yet."
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
              <div className="trends-card-header-actions">
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
                <Button
                  variant="outline"
                  size="sm"
                  className="flagged-export"
                  onClick={exportCsv}
                  disabled={flaggedRows.length === 0}
                >
                  Export CSV
                </Button>
              </div>
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
                      <button className="flagged-open" onClick={() => onOpenJourney(f)}>
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
