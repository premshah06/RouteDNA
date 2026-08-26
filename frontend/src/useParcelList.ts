import { useEffect, useState } from "react";
import { QueryServiceClient } from "@thing-transfer/proto-gen/packagepb/v1/Query_serviceServiceClientPb";
import * as queryPb from "@thing-transfer/proto-gen/packagepb/v1/query_service_pb";
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";
import * as itemPb from "@thing-transfer/proto-gen/packagepb/v1/item_pb";

const { ListParcelsRequest, ParcelStatus } = queryPb;
export { ParcelStatus };
export type StationType = commonPb.StationType;

export interface ParcelRow {
  packageId: string;
  currentStation: StationType;
  lastScanAtMs: number;
  dwellSeconds: number;
  status: queryPb.ParcelStatus;
  activeFlags: alertPb.AlertType[];
  itemName: string;
  itemCategory: itemPb.ItemCategory;
}

export type SortField = "dwell_time" | "detected_at" | "package_id";

export interface ParcelListOptions {
  statusFilter: queryPb.ParcelStatus[];
  page: number;
  pageSize: number;
  sortField: SortField;
  sortDesc: boolean;
}

const QUERY_URL = import.meta.env.VITE_QUERY_URL ?? "http://localhost:8090";
// Dwell time is more time-sensitive than Trends' aggregate stats
// (30s poll) — a package can cross a threshold band within seconds of
// a page sitting open, so poll faster here.
const REFETCH_MS = 15_000;

function toMs(ts: { getSeconds(): number; getNanos(): number } | undefined): number {
  return ts ? ts.getSeconds() * 1000 + ts.getNanos() / 1e6 : Date.now();
}

/** Fetches a paginated, filtered, sorted page of active parcels for
 * the Parcel Explorer tab, refetching on an interval and whenever the
 * filter/sort/pagination options change. */
export function useParcelList(options: ParcelListOptions) {
  const [parcels, setParcels] = useState<ParcelRow[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");

  // statusFilter is a new array reference every render even with the
  // same values — key the effect on the actual values, same rangeKey
  // trick useFacilityStats.ts uses for its object-valued range param.
  const optionsKey = [
    [...options.statusFilter].sort().join(","),
    options.page,
    options.pageSize,
    options.sortField,
    options.sortDesc,
  ].join("|");

  useEffect(() => {
    let cancelled = false;

    function fetchParcels() {
      setStatus((prev) => (prev === "loaded" ? prev : "loading"));
      const client = new QueryServiceClient(QUERY_URL);
      const request = new ListParcelsRequest();
      request.setStatusFilterList(options.statusFilter);
      request.setLimit(options.pageSize);
      request.setOffset(options.page * options.pageSize);
      request.setSortField(options.sortField);
      request.setSortDesc(options.sortDesc);

      client
        .listParcels(request, {})
        .then((response) => {
          if (cancelled) return;
          setParcels(
            response.getParcelsList().map((p) => ({
              packageId: p.getPackageId(),
              currentStation: p.getCurrentStation(),
              lastScanAtMs: toMs(p.getLastScanAt()),
              dwellSeconds: p.getDwellSeconds(),
              status: p.getStatus(),
              activeFlags: p.getActiveFlagsList(),
              itemName: p.getItemName(),
              itemCategory: p.getItemCategory(),
            }))
          );
          setTotalCount(response.getTotalCount());
          setHasMore(response.getHasMore());
          setStatus("loaded");
        })
        .catch(() => {
          if (!cancelled) setStatus("error");
        });
    }

    fetchParcels();
    const interval = setInterval(fetchParcels, REFETCH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optionsKey]);

  return { parcels, totalCount, hasMore, status };
}
