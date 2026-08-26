import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { PackagePosition } from "./useLiveFeed";
import { ITEM_CATEGORY_LABEL, STATION_LABEL, timeAgo } from "./constants";
import "./ScanEventFeed.css";

const ROW_HEIGHT = 32;

interface ScanEventFeedProps {
  events: PackagePosition[];
}

function ScanEventFeed({ events }: ScanEventFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: events.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
  });

  return (
    <section className="scan-event-feed">
      <h3>Live scan events</h3>
      <div className="scan-event-feed-scroll" ref={scrollRef}>
        {events.length === 0 && <div className="chart-empty">No scans yet</div>}
        {events.length > 0 && (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((row) => {
              const e = events[row.index];
              return (
                <div
                  key={row.key}
                  className="scan-event-row"
                  style={{ height: row.size, transform: `translateY(${row.start}px)` }}
                >
                  <span className="scan-event-time">{timeAgo(e.updatedAtMs)}</span>
                  <span className="scan-event-package" title={e.packageId}>
                    {e.packageId.slice(0, 8)}
                  </span>
                  <span className="scan-event-station">{STATION_LABEL[e.station] ?? "—"}</span>
                  <span className="scan-event-item">
                    {e.itemName || ITEM_CATEGORY_LABEL[e.itemCategory] || "Item"}
                  </span>
                  {e.damageDetected && (
                    <span className="scan-event-damage" title="Damage detected">
                      ⚠
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

export default ScanEventFeed;
