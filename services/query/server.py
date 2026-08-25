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
import sys
from datetime import datetime, timezone

import grpc
import pyarrow.compute as pc
import pyarrow.dataset as ds

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gen", "python"))

from packagepb.v1 import (  # noqa: E402
    alert_pb2,
    common_pb2,
    item_pb2,
    query_service_pb2,
    query_service_pb2_grpc,
)
from clickhouse import query_rows  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("query")

LAKE_ROOT = os.environ.get("LAKE_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "data", "lake"))
SCAN_EVENTS_DIR = os.path.join(LAKE_ROOT, "scan_events")


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


def _category_enum(name: str):
    return item_pb2.ItemCategory.Value(name) if name else item_pb2.ITEM_CATEGORY_UNSPECIFIED


class QueryServicer(query_service_pb2_grpc.QueryServiceServicer):
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
            "toUnixTimestamp64Milli(detected_at) AS detected_at_ms "
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
            journey.alerts.append(alert)

        return journey

    async def GetFacilityStats(self, request, context):
        days = {"today": 1, "week": 7, "month": 30}.get(request.range, 1)
        since = f"now() - INTERVAL {days} DAY"

        stats = query_service_pb2.FacilityStats()

        throughput_rows = query_rows(
            "SELECT report_date, sum(scan_count) AS total "
            "FROM daily_station_throughput "
            f"WHERE report_date >= today() - {days} "
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
            f"WHERE report_date >= today() - {days} "
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
            f"WHERE report_date >= today() - {days} "
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
            f"WHERE hour >= {since} "
            "GROUP BY alert_type"
        ):
            entry = stats.alert_breakdown.add()
            entry.alert_type = _alert_type_enum(row["alert_type"])
            entry.count = int(row["c"])

        for row in query_rows(
            "SELECT toHour(hour) AS h, sum(alert_count_merged) AS c FROM ("
            "  SELECT hour, countMerge(alert_count) AS alert_count_merged "
            "  FROM alert_hourly_rollup "
            f"  WHERE hour >= {since} "
            "  GROUP BY hour"
            ") GROUP BY h ORDER BY h"
        ):
            entry = stats.busiest_hours.add()
            entry.hour = int(row["h"])
            entry.count = int(row["c"])

        for row in query_rows(
            "SELECT package_id, alert_type, station, "
            "toUnixTimestamp64Milli(detected_at) AS detected_at_ms "
            f"FROM alerts WHERE detected_at >= {since} "
            "ORDER BY detected_at DESC LIMIT 20"
        ):
            entry = stats.recent_flagged.add()
            entry.package_id = row["package_id"]
            entry.alert_type = _alert_type_enum(row["alert_type"])
            entry.station = _station_enum(row["station"])
            _set_timestamp(entry.detected_at, datetime.fromtimestamp(int(row["detected_at_ms"]) / 1000, tz=timezone.utc))

        return stats


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
