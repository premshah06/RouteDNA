import { useMemo, useState } from "react";
import type { SortingState } from "@tanstack/react-table";
import { useParcelList, ParcelStatus, type SortField } from "./useParcelList";
import ParcelGrid from "./ParcelGrid";
import { Input } from "@/components/ui/input";
import "./ParcelExplorerView.css";

const STATUS_FACETS: { status: number; label: string }[] = [
  { status: ParcelStatus.PARCEL_STATUS_IN_TRANSIT, label: "In Transit" },
  { status: ParcelStatus.PARCEL_STATUS_DELAYED, label: "Delayed" },
  { status: ParcelStatus.PARCEL_STATUS_STUCK, label: "Stuck" },
];

const PAGE_SIZE = 50;

// ParcelGrid's TanStack Table column ids map 1:1 to ListParcelsRequest's
// sort_field allowlist except "lastScanAt", which corresponds to the
// backend's "detected_at" field name (last_scan_at on the wire).
const COLUMN_TO_SORT_FIELD: Record<string, SortField> = {
  packageId: "package_id",
  dwellSeconds: "dwell_time",
  lastScanAt: "detected_at",
};

interface ParcelExplorerViewProps {
  onSelectPackage: (packageId: string) => void;
}

function ParcelExplorerView({ onSelectPackage }: ParcelExplorerViewProps) {
  const [statusFilter, setStatusFilter] = useState<Set<number>>(new Set());
  const [searchText, setSearchText] = useState("");
  const [page, setPage] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([{ id: "dwellSeconds", desc: true }]);

  const sortField = sorting.length > 0 ? COLUMN_TO_SORT_FIELD[sorting[0].id] ?? "dwell_time" : "dwell_time";
  const sortDesc = sorting.length > 0 ? sorting[0].desc : true;

  const { parcels, totalCount, hasMore, status } = useParcelList({
    statusFilter: Array.from(statusFilter),
    page,
    pageSize: PAGE_SIZE,
    sortField,
    sortDesc,
  });

  const visibleParcels = useMemo(() => {
    const needle = searchText.trim().toLowerCase();
    if (!needle) return parcels;
    return parcels.filter((p) => p.packageId.toLowerCase().includes(needle) || p.itemName.toLowerCase().includes(needle));
  }, [parcels, searchText]);

  function toggleFacet(facetStatus: number) {
    setPage(0);
    setStatusFilter((prev) => {
      const next = new Set(prev);
      if (next.has(facetStatus)) next.delete(facetStatus);
      else next.add(facetStatus);
      return next;
    });
  }

  return (
    <main className="parcel-explorer">
      <div className="parcel-explorer-toolbar">
        <Input
          placeholder="Search parcels or item names…"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="parcel-search-input"
        />
        <div className="parcel-facets">
          {STATUS_FACETS.map((f) => (
            <button
              key={f.status}
              className={`parcel-facet${statusFilter.has(f.status) ? " active" : ""}`}
              onClick={() => toggleFacet(f.status)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {status === "loading" && parcels.length === 0 && <div className="chart-empty">Loading parcels…</div>}
      {status === "error" && <div className="chart-empty error">Couldn't load parcels.</div>}

      {parcels.length > 0 || status === "loaded" ? (
        <>
          <ParcelGrid
            parcels={visibleParcels}
            sorting={sorting}
            onSortingChange={(updater) => {
              setPage(0);
              setSorting(updater);
            }}
            onSelectPackage={onSelectPackage}
          />
          <div className="parcel-pagination">
            <span className="parcel-pagination-count">
              {totalCount === 0 ? "No parcels" : `${page * PAGE_SIZE + 1}–${page * PAGE_SIZE + parcels.length} of ${totalCount}`}
            </span>
            <div className="parcel-pagination-controls">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                ← Prev
              </button>
              <button disabled={!hasMore} onClick={() => setPage((p) => p + 1)}>
                Next →
              </button>
            </div>
          </div>
        </>
      ) : null}
    </main>
  );
}

export default ParcelExplorerView;
