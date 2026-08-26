"""Query service: unary gRPC reads backing the journey side panel and
the Trends tab.

Unlike live_feed (Checkpoint 7), this service holds no state and
consumes nothing from Kafka — every RPC here is a read against data
that already exists: the Parquet lake (raw scan history, Checkpoint 6)
and ClickHouse (alerts + daily/hourly rollups, Checkpoints 6 and 8).
Both were built as this platform's system of record specifically so a
service like this wouldn't need to reconstruct history itself.
"""

import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import grpc
import pyarrow.compute as pc
import pyarrow.dataset as ds

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gen", "python"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from packagepb.v1 import (  # noqa: E402
    alert_pb2,
    common_pb2,
    item_pb2,
    live_feed_service_pb2,
    live_feed_service_pb2_grpc,
    query_service_pb2,
    query_service_pb2_grpc,
    scan_event_pb2,
)
from clickhouse import query_rows  # noqa: E402
from thresholds import DELAYED_THRESHOLD_MS, STUCK_THRESHOLD_MS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("query")

LAKE_ROOT = os.environ.get("LAKE_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "lake"))
SCAN_EVENTS_DIR = os.path.join(LAKE_ROOT, "scan_events")
LIVE_FEED_URL = os.environ.get("LIVE_FEED_URL", "localhost:50052")

# Alert types that can appear as a ParcelSummary.active_flags entry —
# STUCK_PACKAGE is deliberately excluded here since ListParcels derives
# "stuck" from live dwell time directly (see ParcelStatus.PARCEL_STATUS_STUCK
# in _classify_status), not from whether Flink's detector has already
# fired an alert for it.
_FLAG_ALERT_TYPES = (alert_pb2.ALERT_TYPE_MISROUTING, alert_pb2.ALERT_TYPE_DAMAGE)

_PARCEL_SORT_FIELDS = {"dwell_time", "detected_at", "package_id"}
_LIST_PARCELS_MAX_LIMIT = 200
# Well beyond STUCK_THRESHOLD_MS (10 min) — any flag-relevant alert for
# a package still live in positions is recent; this just bounds the
# alerts-table scan, not the cross-check's actual staleness judgment.
_ALERT_LOOKBACK_MINUTES = 60


def _set_timestamp(pb_timestamp, dt: datetime) -> None:
    pb_timestamp.FromDatetime(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _station_enum(name: str):
    # ClickHouse/lake both store the enum's string name (e.g.
    # "STATION_TYPE_SORT_A") — Value() raises on an unrecognized name,
    # which is preferable to silently mapping to UNSPECIFIED and hiding
    # a real data problem (a station renamed on one side but not the other).
    return common_pb2.StationType.Value(name) if name else common_pb2.STATION_TYPE_UNSPECIFIED


def _alert_type_enum(name: str):
    return alert_pb2.AlertType.Value(name) if name else alert_pb2.ALERT_TYPE_UNSPECIFIED


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DateRange:
    """Resolves a GetFacilityStatsRequest's range selection into the two
    SQL boundary expressions the queries below need — one for
    Date-typed columns (report_date), one for DateTime-typed columns
    (hour, detected_at). A custom start_date/end_date (validated
    "YYYY-MM-DD" — ClickHouse identifiers/expressions can't be
    parameterized through query_rows' plain string interpolation, so a
    strict format check here is the injection guard) takes precedence
    over the preset when both are supplied; otherwise falls back to the
    existing "today"/"week"/"month" day-count behavior unchanged."""

    def __init__(self, request):
        start, end = request.start_date, request.end_date
        if start and end:
            if not (_DATE_RE.match(start) and _DATE_RE.match(end)):
                raise ValueError("start_date/end_date must be YYYY-MM-DD")
            self.report_date_floor = f"toDate('{start}')"
            self.datetime_floor = f"toDateTime('{start} 00:00:00')"
            # Inclusive end-of-day, so a single-day custom range (start
            # == end) still includes that whole day's data.
            self.datetime_ceiling = f"toDateTime('{end} 23:59:59')"
        else:
            days = {"today": 1, "week": 7, "month": 30}.get(request.range, 1)
            self.report_date_floor = f"today() - {days}"
            self.datetime_floor = f"now() - INTERVAL {days} DAY"
            self.datetime_ceiling = "now()"


def _category_enum(name: str):
    return item_pb2.ItemCategory.Value(name) if name else item_pb2.ITEM_CATEGORY_UNSPECIFIED


def _classify_status(dwell_ms: int) -> int:
    if dwell_ms >= STUCK_THRESHOLD_MS:
        return query_service_pb2.PARCEL_STATUS_STUCK
    if dwell_ms >= DELAYED_THRESHOLD_MS:
        return query_service_pb2.PARCEL_STATUS_DELAYED
    return query_service_pb2.PARCEL_STATUS_IN_TRANSIT


class QueryServicer(query_service_pb2_grpc.QueryServiceServicer):
    def __init__(self):
        # Constructed once, reused across calls — ListParcels is called
        # repeatedly (grid pagination, re-sorting, polling), unlike
        # GetPackageJourney's one-shot-per-panel-open pattern, so a
        # fresh channel per call would be wasteful here.
        self._live_feed_channel = grpc.aio.insecure_channel(LIVE_FEED_URL)
        self._live_feed_stub = live_feed_service_pb2_grpc.LiveFeedServiceStub(self._live_feed_channel)

    # grpc.aio requires servicer methods to be coroutines. Each one
    # below does blocking I/O (httpx, pyarrow) rather than awaiting
    # anything internally — acceptable here since this service is
    # low-QPS request/response (a panel open, a tab load), not a
    # throughput-sensitive streaming path like live_feed.
    async def GetPackageJourney(self, request, context):
        package_id = request.package_id
        journey = query_service_pb2.PackageJourney(package_id=package_id)

        for scan in _read_scans_for_package(package_id):
            journey.scans.append(scan)

        for row in query_rows(
            "SELECT alert_id, package_id, alert_type, severity, station, message, "
            "toUnixTimestamp64Milli(detected_at) AS detected_at_ms, "
            "stuck_duration_seconds, threshold_seconds, expected_station, "
            "actual_station, path_so_far, damage_type, damage_confidence "
            f"FROM alerts WHERE package_id = '{_escape(package_id)}' "
            "ORDER BY detected_at DESC"
        ):
            alert = alert_pb2.Alert(
                alert_id=row["alert_id"],
                package_id=row["package_id"],
                alert_type=_alert_type_enum(row["alert_type"]),
                severity=alert_pb2.Severity.Value(row["severity"]) if row["severity"] else alert_pb2.SEVERITY_UNSPECIFIED,
                station=_station_enum(row["station"]),
                message=row["message"],
            )
            _set_timestamp(alert.detected_at, datetime.fromtimestamp(int(row["detected_at_ms"]) / 1000, tz=timezone.utc))

            # Populate whichever detail branch matches alert_type — the
            # other columns are just table defaults (0/''/[]) for this
            # row, same as decode_alert_row never having set them.
            if alert.alert_type == alert_pb2.ALERT_TYPE_STUCK_PACKAGE:
                alert.stuck_detail.stuck_duration_seconds = int(row["stuck_duration_seconds"])
                alert.stuck_detail.threshold_seconds = int(row["threshold_seconds"])
            elif alert.alert_type == alert_pb2.ALERT_TYPE_MISROUTING:
                if row["expected_station"]:
                    alert.misrouting_detail.expected_station = _station_enum(row["expected_station"])
                if row["actual_station"]:
                    alert.misrouting_detail.actual_station = _station_enum(row["actual_station"])
                for station_name in row["path_so_far"]:
                    alert.misrouting_detail.path_so_far.append(_station_enum(station_name))
            elif alert.alert_type == alert_pb2.ALERT_TYPE_DAMAGE:
                if row["damage_type"]:
                    alert.damage_detail.damage_type = scan_event_pb2.DamageType.Value(row["damage_type"])
                alert.damage_detail.confidence = float(row["damage_confidence"])

            journey.alerts.append(alert)

        return journey

    async def GetFacilityStats(self, request, context):
        try:
            date_range = DateRange(request)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return
        report_date_floor = date_range.report_date_floor
        dt_floor = date_range.datetime_floor
        dt_ceiling = date_range.datetime_ceiling

        stats = query_service_pb2.FacilityStats()

        throughput_rows = query_rows(
            "SELECT report_date, sum(scan_count) AS total "
            "FROM daily_station_throughput "
            f"WHERE report_date >= {report_date_floor} "
            "GROUP BY report_date ORDER BY report_date"
        )
        stats.throughput_total = sum(int(r["total"]) for r in throughput_rows)
        for row in throughput_rows:
            point = stats.throughput_series.add()
            _set_timestamp(point.bucket, datetime.strptime(row["report_date"], "%Y-%m-%d"))
            point.count = int(row["total"])

        damage_rows = query_rows(
            "SELECT station, sum(scan_count) AS scans, sum(damage_count) AS damage "
            "FROM daily_station_throughput "
            f"WHERE report_date >= {report_date_floor} "
            "GROUP BY station"
        )
        total_scans = sum(int(r["scans"]) for r in damage_rows)
        total_damage = sum(int(r["damage"]) for r in damage_rows)
        stats.damage_rate = (total_damage / total_scans) if total_scans else 0.0
        for row in damage_rows:
            entry = stats.damage_by_station.add()
            entry.station = _station_enum(row["station"])
            scans = int(row["scans"])
            entry.damage_rate = (int(row["damage"]) / scans) if scans else 0.0

        category_rows = query_rows(
            "SELECT item_category, sum(scan_count) AS scans, sum(damage_count) AS damage "
            "FROM daily_damage_rate_by_category "
            f"WHERE report_date >= {report_date_floor} "
            "GROUP BY item_category"
        )
        for row in category_rows:
            entry = stats.damage_by_category.add()
            entry.item_category = _category_enum(row["item_category"])
            scans = int(row["scans"])
            entry.damage_rate = (int(row["damage"]) / scans) if scans else 0.0

        for row in query_rows(
            "SELECT alert_type, countMerge(alert_count) AS c "
            "FROM alert_hourly_rollup "
            f"WHERE hour >= {dt_floor} AND hour <= {dt_ceiling} "
            "GROUP BY alert_type"
        ):
            entry = stats.alert_breakdown.add()
            entry.alert_type = _alert_type_enum(row["alert_type"])
            entry.count = int(row["c"])

        for row in query_rows(
            "SELECT toHour(hour) AS h, sum(alert_count_merged) AS c FROM ("
            "  SELECT hour, countMerge(alert_count) AS alert_count_merged "
            "  FROM alert_hourly_rollup "
            f"  WHERE hour >= {dt_floor} AND hour <= {dt_ceiling} "
            "  GROUP BY hour"
            ") GROUP BY h ORDER BY h"
        ):
            entry = stats.busiest_hours.add()
            entry.hour = int(row["h"])
            entry.count = int(row["c"])

        # One point per (hour, alert_type), unlike busiest_hours above
        # which collapses to hour-of-day — this is the real timestamped
        # trend line for the "alerts over time" chart.
        for row in query_rows(
            "SELECT hour, alert_type, countMerge(alert_count) AS c "
            "FROM alert_hourly_rollup "
            f"WHERE hour >= {dt_floor} AND hour <= {dt_ceiling} "
            "GROUP BY hour, alert_type ORDER BY hour"
        ):
            entry = stats.alert_trend.add()
            _set_timestamp(entry.bucket, datetime.strptime(row["hour"], "%Y-%m-%d %H:%M:%S"))
            entry.alert_type = _alert_type_enum(row["alert_type"])
            entry.count = int(row["c"])

        for row in query_rows(
            "SELECT package_id, alert_type, station, "
            "toUnixTimestamp64Milli(detected_at) AS detected_at_ms "
            f"FROM alerts WHERE detected_at >= {dt_floor} AND detected_at <= {dt_ceiling} "
            "ORDER BY detected_at DESC LIMIT 20"
        ):
            entry = stats.recent_flagged.add()
            entry.package_id = row["package_id"]
            entry.alert_type = _alert_type_enum(row["alert_type"])
            entry.station = _station_enum(row["station"])
            _set_timestamp(entry.detected_at, datetime.fromtimestamp(int(row["detected_at_ms"]) / 1000, tz=timezone.utc))

        return stats

    async def GetStationStats(self, request, context):
        if request.station == common_pb2.STATION_TYPE_UNSPECIFIED:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "station is required")
            return
        try:
            date_range = DateRange(request)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return
        report_date_floor = date_range.report_date_floor
        dt_floor = date_range.datetime_floor
        dt_ceiling = date_range.datetime_ceiling
        station_name = common_pb2.StationType.Name(request.station)

        stats = query_service_pb2.StationStats(station=request.station)

        throughput_rows = query_rows(
            "SELECT report_date, sum(scan_count) AS scans, sum(damage_count) AS damage "
            "FROM daily_station_throughput "
            f"WHERE report_date >= {report_date_floor} AND station = '{station_name}' "
            "GROUP BY report_date ORDER BY report_date"
        )
        total_scans = sum(int(r["scans"]) for r in throughput_rows)
        total_damage = sum(int(r["damage"]) for r in throughput_rows)
        stats.damage_rate = (total_damage / total_scans) if total_scans else 0.0
        for row in throughput_rows:
            point = stats.throughput_series.add()
            _set_timestamp(point.bucket, datetime.strptime(row["report_date"], "%Y-%m-%d"))
            point.count = int(row["scans"])

        for row in query_rows(
            "SELECT alert_type, countMerge(alert_count) AS c "
            "FROM alert_hourly_rollup "
            f"WHERE hour >= {dt_floor} AND hour <= {dt_ceiling} AND station = '{station_name}' "
            "GROUP BY alert_type"
        ):
            entry = stats.alert_breakdown.add()
            entry.alert_type = _alert_type_enum(row["alert_type"])
            entry.count = int(row["c"])

        return stats

    async def ListParcels(self, request, context):
        if request.sort_field and request.sort_field not in _PARCEL_SORT_FIELDS:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"sort_field must be one of {sorted(_PARCEL_SORT_FIELDS)}",
            )
            return
        sort_field = request.sort_field or "dwell_time"
        limit = min(request.limit, _LIST_PARCELS_MAX_LIMIT) if request.limit else _LIST_PARCELS_MAX_LIMIT
        offset = request.offset

        # Ground truth for "what's currently in the facility" — a
        # package with no live position has left and is out of scope
        # for this grid. See live_feed_service.proto's ListPositions.
        live_response = await self._live_feed_stub.ListPositions(live_feed_service_pb2.ListPositionsRequest())
        positions = list(live_response.positions)

        # Latest alert per (package_id, alert_type), for the flags this
        # RPC can cross-check against live state. STUCK_PACKAGE is
        # excluded — see _FLAG_ALERT_TYPES. Bounded to a recent window
        # (not the full 90-day TTL): a package with no live position
        # older than POSITION_STALE_MS has already left live_feed's
        # positions dict entirely (see useLiveFeed.ts), so any flag
        # candidate here is necessarily attached to a package seen
        # recently — an unbounded scan would re-read the whole alerts
        # table on every 15s-polled ListParcels call for no benefit.
        alert_type_names = ", ".join(f"'{alert_pb2.AlertType.Name(t)}'" for t in _FLAG_ALERT_TYPES)
        latest_alerts: dict[tuple[str, int], int] = {}
        for row in query_rows(
            "SELECT package_id, alert_type, "
            "toUnixTimestamp64Milli(argMax(detected_at, detected_at)) AS detected_at_ms "
            f"FROM alerts WHERE alert_type IN ({alert_type_names}) "
            f"AND detected_at >= now() - INTERVAL {_ALERT_LOOKBACK_MINUTES} MINUTE "
            "GROUP BY package_id, alert_type"
        ):
            key = (row["package_id"], _alert_type_enum(row["alert_type"]))
            latest_alerts[key] = int(row["detected_at_ms"])

        now_ms = time.time() * 1000
        rows = []
        for position in positions:
            updated_at_ms = position.updated_at.ToMilliseconds()
            dwell_ms = max(0, int(now_ms - updated_at_ms))
            status = _classify_status(dwell_ms)

            active_flags = []
            for alert_type in _FLAG_ALERT_TYPES:
                detected_at_ms = latest_alerts.get((position.package_id, alert_type))
                # An alert only counts as still active if no scan has
                # occurred since it fired — a package that's moved on
                # since a stale alert should not show that flag.
                if detected_at_ms is not None and detected_at_ms >= updated_at_ms:
                    active_flags.append(alert_type)

            rows.append(
                {
                    "package_id": position.package_id,
                    "current_station": position.station,
                    "updated_at_ms": updated_at_ms,
                    "dwell_ms": dwell_ms,
                    "status": status,
                    "active_flags": active_flags,
                    "item_name": position.item_name,
                    "item_category": position.item_category,
                }
            )

        if request.status_filter:
            wanted = set(request.status_filter)
            rows = [r for r in rows if r["status"] in wanted]

        sort_key = {
            "dwell_time": lambda r: r["dwell_ms"],
            "detected_at": lambda r: r["updated_at_ms"],
            "package_id": lambda r: r["package_id"],
        }[sort_field]
        rows.sort(key=sort_key, reverse=request.sort_desc)

        total_count = len(rows)
        page = rows[offset : offset + limit]

        response = query_service_pb2.ListParcelsResponse(
            total_count=total_count,
            has_more=(offset + len(page)) < total_count,
        )
        for row in page:
            entry = response.parcels.add()
            entry.package_id = row["package_id"]
            entry.current_station = row["current_station"]
            _set_timestamp(entry.last_scan_at, datetime.fromtimestamp(row["updated_at_ms"] / 1000, tz=timezone.utc))
            entry.dwell_seconds = row["dwell_ms"] // 1000
            entry.status = row["status"]
            entry.active_flags.extend(row["active_flags"])
            entry.item_name = row["item_name"]
            entry.item_category = row["item_category"]

        return response


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _read_scans_for_package(package_id: str) -> list:
    """Scans the whole lake for one package_id. A package's journey can
    span a day boundary (e.g. intake at 23:58, dispatch at 00:05), so
    unlike the batch layer's read_scan_events_for_date this can't be
    scoped to a single day up front — filter pushdown (pc.field ==)
    keeps this from materializing more than the matching rows even
    though every partition file gets opened."""
    if not os.path.isdir(SCAN_EVENTS_DIR):
        return []
    dataset = ds.dataset(SCAN_EVENTS_DIR, format="parquet", partitioning="hive")
    table = dataset.to_table(filter=pc.field("package_id") == package_id)
    table = table.sort_by("scanned_at")

    scans = []
    for row in table.to_pylist():
        scan = query_service_pb2.JourneyScan(
            event_id=row["event_id"],
            station=_station_enum(row["station"]),
            scanner_id=row["scanner_id"],
            result=row["result"],
            damage_type=row["damage_type"] or "",
            damage_confidence=row["damage_confidence"] or 0.0,
        )
        _set_timestamp(scan.scanned_at, row["scanned_at"])
        scans.append(scan)
    return scans


async def serve(port: int = 50053) -> None:
    server = grpc.aio.server()
    query_service_pb2_grpc.add_QueryServiceServicer_to_server(QueryServicer(), server)
    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)
    logger.info("query service listening on %s", listen_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    import asyncio

    asyncio.run(serve())
