import type { ColumnDef } from "@tanstack/react-table";
import type { ParcelRow } from "./useParcelList";
import { ParcelStatus } from "./useParcelList";
import { ALERT_TYPE_ICON, ALERT_TYPE_LABEL, ITEM_CATEGORY_LABEL, STATION_LABEL, timeAgo } from "./constants";
import { Badge } from "@/components/ui/badge";

const STATUS_LABEL: Record<number, string> = {
  [ParcelStatus.PARCEL_STATUS_UNSPECIFIED]: "Unknown",
  [ParcelStatus.PARCEL_STATUS_IN_TRANSIT]: "In Transit",
  [ParcelStatus.PARCEL_STATUS_DELAYED]: "Delayed",
  [ParcelStatus.PARCEL_STATUS_STUCK]: "Stuck",
};

const STATUS_CLASS: Record<number, string> = {
  [ParcelStatus.PARCEL_STATUS_UNSPECIFIED]: "info",
  [ParcelStatus.PARCEL_STATUS_IN_TRANSIT]: "info",
  [ParcelStatus.PARCEL_STATUS_DELAYED]: "warning",
  [ParcelStatus.PARCEL_STATUS_STUCK]: "critical",
};

function formatDwell(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export const parcelColumns: ColumnDef<ParcelRow>[] = [
  {
    accessorKey: "packageId",
    header: "Parcel ID",
    cell: ({ row }) => (
      <span className="parcel-cell-id" title={row.original.packageId}>
        {row.original.packageId.slice(0, 8)}
      </span>
    ),
  },
  {
    id: "itemName",
    header: "Item",
    cell: ({ row }) => (
      <span className="parcel-cell-item">
        {row.original.itemName || ITEM_CATEGORY_LABEL[row.original.itemCategory] || "Item"}
      </span>
    ),
  },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant="outline" className={`parcel-status-badge status-${STATUS_CLASS[row.original.status]}`}>
        {STATUS_LABEL[row.original.status] ?? "Unknown"}
      </Badge>
    ),
  },
  {
    id: "activeFlags",
    header: "Flags",
    cell: ({ row }) =>
      row.original.activeFlags.length > 0 ? (
        <span className="parcel-cell-flags">
          {row.original.activeFlags.map((flag) => (
            <span key={flag} className="parcel-flag-chip" title={ALERT_TYPE_LABEL[flag] ?? "Alert"}>
              {ALERT_TYPE_ICON[flag] ?? "?"}
            </span>
          ))}
        </span>
      ) : (
        <span className="parcel-cell-flags-empty">—</span>
      ),
  },
  {
    id: "currentStation",
    header: "Station",
    cell: ({ row }) => <span className="parcel-cell-station">{STATION_LABEL[row.original.currentStation] ?? "—"}</span>,
  },
  {
    accessorKey: "dwellSeconds",
    header: "Dwell",
    cell: ({ row }) => <span className="parcel-cell-dwell">{formatDwell(row.original.dwellSeconds)}</span>,
  },
  {
    id: "lastScanAt",
    header: "Last Scan",
    cell: ({ row }) => <span className="parcel-cell-time">{timeAgo(row.original.lastScanAtMs)}</span>,
  },
];
