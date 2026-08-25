import { useMemo, useState } from "react";
import { useLiveFeed, type AlertItem } from "./useLiveFeed";
import { useFacilityStats } from "./useFacilityStats";
import { useLiveDamageRate } from "./useLiveDamageRate";
import { ALERT_TYPE_LABEL, STATION_LABEL, type StationType } from "./constants";
import LiveView from "./LiveView";
import AlertsPanel from "./AlertsPanel";
import TrendsView from "./TrendsView";
import JourneyPanel from "./JourneyPanel";
import "./App.css";

type Tab = "live" | "trends";

function App() {
  const [tab, setTab] = useState<Tab>("live");
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null);
  // Shared cross-navigation target: set when the user clicks a station
  // in one tab, read by the other tab to highlight/filter to it. Lives
  // here (not inside either tab's own component) since it has to
  // survive a tab switch.
  const [focusedStation, setFocusedStation] = useState<StationType | null>(null);
  const { positions, alerts, status } = useLiveFeed();
  // "today" here is only for the header KPI strip's throughput number —
  // the Trends tab manages its own range independently.
  const { stats: todayStats } = useFacilityStats("today");
  // Damage rate uses the live rolling-window signal instead of
  // todayStats.damageRate: that batch-sourced number is only as fresh
  // as the last Dagster run and reads 0% until "today" has one — see
  // useLiveDamageRate's docstring for why no live alert exists to read
  // this from directly.
  const { damageRate: liveDamageRate } = useLiveDamageRate(positions);

  // The live stream (useLiveFeed's `alerts`) only carries alerts that
  // arrived after this tab connected — a fresh page load legitimately
  // shows an empty panel even though the facility has plenty of
  // history, which reads as broken rather than quiet. Seed the panel
  // with QueryService's recentFlagged (same data Trends' table uses)
  // so it opens already populated, then let live alerts layer on top —
  // live wins on id collision since it carries the real severity/message
  // recentFlagged doesn't have.
  const seededAlerts: AlertItem[] = useMemo(
    () =>
      (todayStats?.recentFlagged ?? []).map((f) => ({
        alertId: `seed-${f.packageId}-${f.detectedAtMs}`,
        packageId: f.packageId,
        alertType: f.alertType,
        severity: 2, // SEVERITY_WARNING — recentFlagged has no severity field to read
        station: f.station,
        message: `${ALERT_TYPE_LABEL[f.alertType] ?? "Alert"} at ${STATION_LABEL[f.station] ?? "unknown station"}`,
        detectedAtMs: f.detectedAtMs,
      })),
    [todayStats]
  );

  const displayedAlerts = useMemo(() => {
    // Dedup by packageId, not alertId (seeded rows use a synthetic id
    // that never matches a live one) — a package already carrying a
    // live alert shouldn't also show its seeded counterpart once real
    // data arrives for it.
    const livePackageIds = new Set(alerts.map((a) => a.packageId));
    const seededOnly = seededAlerts.filter((a) => !livePackageIds.has(a.packageId));
    return [...alerts, ...seededOnly].sort((a, b) => b.detectedAtMs - a.detectedAtMs);
  }, [alerts, seededAlerts]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Facility Live View</h1>
        <nav className="app-tabs">
          <button className={`app-tab${tab === "live" ? " active" : ""}`} onClick={() => setTab("live")}>
            Live
          </button>
          <button className={`app-tab${tab === "trends" ? " active" : ""}`} onClick={() => setTab("trends")}>
            Trends
          </button>
        </nav>
        <span className={`status-badge status-${status}`}>{status}</span>
      </header>

      {tab === "live" ? (
        <>
          <LiveView
            positions={positions}
            alerts={alerts}
            throughputTotal={todayStats?.throughputTotal ?? 0}
            damageRate={liveDamageRate}
            onSelectPackage={setSelectedPackageId}
            focusedStation={focusedStation}
            onFocusStation={(station) => {
              setFocusedStation(station);
              setTab("trends");
            }}
          />
          <AlertsPanel alerts={displayedAlerts} positions={positions} onSelectPackage={setSelectedPackageId} />
        </>
      ) : (
        <TrendsView
          onOpenJourney={(packageId) => {
            setTab("live");
            setSelectedPackageId(packageId);
          }}
          focusedStation={focusedStation}
          onFocusStation={(station) => {
            setFocusedStation(station);
            setTab("live");
          }}
          onClearFocus={() => setFocusedStation(null)}
        />
      )}

      {selectedPackageId && (
        <JourneyPanel
          packageId={selectedPackageId}
          itemName={positions.get(selectedPackageId)?.itemName}
          onClose={() => setSelectedPackageId(null)}
        />
      )}
    </div>
  );
}

export default App;
