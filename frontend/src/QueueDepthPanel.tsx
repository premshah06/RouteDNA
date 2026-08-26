import { STATIONS, type StationType } from "./constants";
import type { PackagePosition } from "./useLiveFeed";
import { useQueueDepthHistory } from "./useQueueDepthHistory";
import { MultiLineChart, SERIES } from "./charts";
import "./QueueDepthPanel.css";

interface QueueDepthPanelProps {
  packagesByStation: Map<StationType, PackagePosition[]>;
}

function QueueDepthPanel({ packagesByStation }: QueueDepthPanelProps) {
  const samples = useQueueDepthHistory(packagesByStation);

  return (
    <section className="queue-depth-panel">
      <h3>Queue depth · last 30 min</h3>
      <div className="queue-depth-grid">
        {STATIONS.map((station, i) => {
          const points = samples.map((s) => ({
            label: new Date(s.atMs).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
            value: s.counts[station.type] ?? 0,
          }));
          const current = points.length > 0 ? points[points.length - 1].value : 0;
          return (
            <div key={station.type} className="queue-depth-cell">
              <div className="queue-depth-cell-header">
                <span className="queue-depth-cell-label">{station.label}</span>
                <span className="queue-depth-cell-value">{current}</span>
              </div>
              <MultiLineChart
                series={[{ name: station.label, color: SERIES[i % SERIES.length], points }]}
                compact
                height={40}
                emptyHint=""
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default QueueDepthPanel;
