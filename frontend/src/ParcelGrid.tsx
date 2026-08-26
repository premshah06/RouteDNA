import { useRef } from "react";
import { useReactTable, getCoreRowModel, flexRender, type SortingState, type OnChangeFn } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ParcelRow } from "./useParcelList";
import { parcelColumns } from "./parcelColumns";
import "./ParcelGrid.css";

const ROW_HEIGHT = 40;

interface ParcelGridProps {
  parcels: ParcelRow[];
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
  onSelectPackage: (packageId: string) => void;
}

function ParcelGrid({ parcels, sorting, onSortingChange, onSelectPackage }: ParcelGridProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const table = useReactTable({
    data: parcels,
    columns: parcelColumns,
    state: { sorting },
    onSortingChange,
    manualSorting: true,
    getCoreRowModel: getCoreRowModel(),
  });

  const rows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
  });

  return (
    <div className="parcel-grid">
      <div className="parcel-grid-header-row">
        {table.getHeaderGroups().map((headerGroup) =>
          headerGroup.headers.map((header) => {
            const sortable = header.column.id !== "activeFlags" && header.column.id !== "itemName";
            const sortDir = header.column.getIsSorted();
            return (
              <div
                key={header.id}
                className={`parcel-grid-header-cell${sortable ? " sortable" : ""}`}
                onClick={sortable ? header.column.getToggleSortingHandler() : undefined}
              >
                {flexRender(header.column.columnDef.header, header.getContext())}
                {sortDir === "asc" && " ▲"}
                {sortDir === "desc" && " ▼"}
              </div>
            );
          })
        )}
      </div>
      <div className="parcel-grid-scroll" ref={scrollRef}>
        {rows.length === 0 && <div className="chart-empty">No parcels match this filter.</div>}
        {rows.length > 0 && (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index];
              return (
                <div
                  key={row.id}
                  className="parcel-grid-row"
                  style={{ height: virtualRow.size, transform: `translateY(${virtualRow.start}px)` }}
                  onClick={() => onSelectPackage(row.original.packageId)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <div key={cell.id} className="parcel-grid-cell">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default ParcelGrid;
