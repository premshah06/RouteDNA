"""Checkpoint 8: batch layer.

Streaming (Checkpoints 4-6) already covers real-time alerts and
hourly rollups — see warehouse/init/02_alert_rollups.sql. This batch
layer exists for what streaming shouldn't do on the hot path: full-day
aggregates and a raw-vs-derived reconciliation check, computed by
reprocessing the day's raw Parquet from the lake rather than reading
Kafka. Classic lambda-architecture batch layer: it recomputes from
source-of-truth data, so a bug in a streaming job doesn't corrupt
history it can't self-correct.

Each asset is partitioned by day (DailyPartitionsDefinition) and reads
exactly that day's lake partition — a Dagster backfill for a past date
range re-reads the lake for those specific days rather than requiring
a special "historical mode."
"""

from collections import Counter, defaultdict

import dagster as dg

from . import clickhouse, lake
from .catalog import item_categories

daily_partitions = dg.DailyPartitionsDefinition(start_date="2026-08-01")


@dg.asset(partitions_def=daily_partitions, group_name="batch_reports")
def daily_station_throughput(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Per-station scan volume for one day — the metric a stuck-package
    hourly rollup can't answer on its own: "was Sort B busier than
    usual today, end to end," not "is anything stuck right now."""
    report_date = context.partition_key
    table = lake.read_scan_events_for_date(report_date)

    by_station = defaultdict(lambda: {"scans": 0, "packages": set(), "damage": 0, "unreadable": 0})
    stations = table.column("station").to_pylist()
    packages = table.column("package_id").to_pylist()
    results = table.column("result").to_pylist()

    for station, package_id, result in zip(stations, packages, results):
        bucket = by_station[station]
        bucket["scans"] += 1
        bucket["packages"].add(package_id)
        if result == "SCAN_RESULT_DAMAGE_DETECTED":
            bucket["damage"] += 1
        elif result == "SCAN_RESULT_UNREADABLE":
            bucket["unreadable"] += 1

    rows = [
        {
            "report_date": report_date,
            "station": station,
            "scan_count": b["scans"],
            "unique_packages": len(b["packages"]),
            "damage_count": b["damage"],
            "unreadable_count": b["unreadable"],
        }
        for station, b in by_station.items()
    ]
    inserted = clickhouse.insert_rows(
        "daily_station_throughput",
        ["report_date", "station", "scan_count", "unique_packages", "damage_count", "unreadable_count"],
        rows,
    )
    return dg.MaterializeResult(
        metadata={"report_date": report_date, "stations_reported": len(rows), "rows_inserted": inserted}
    )


@dg.asset(partitions_def=daily_partitions, group_name="batch_reports")
def daily_damage_rate_by_category(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Damage rate needs a join against the item catalog that the
    streaming path never does (ScanEvent only carries item_id, not
    category — see station_sim/simulator.py) — a full-day batch pass is
    the natural place for this join, not a per-event streaming lookup."""
    report_date = context.partition_key
    table = lake.read_scan_events_for_date(report_date)
    categories = item_categories()

    scans = Counter()
    damage = Counter()
    item_ids = table.column("item_id").to_pylist()
    results = table.column("result").to_pylist()

    for item_id, result in zip(item_ids, results):
        category = categories.get(item_id, "ITEM_CATEGORY_UNSPECIFIED") if item_id else "ITEM_CATEGORY_UNSPECIFIED"
        scans[category] += 1
        if result == "SCAN_RESULT_DAMAGE_DETECTED":
            damage[category] += 1

    rows = [
        {
            "report_date": report_date,
            "item_category": category,
            "scan_count": count,
            "damage_count": damage[category],
            "damage_rate": damage[category] / count if count else 0.0,
        }
        for category, count in scans.items()
    ]
    inserted = clickhouse.insert_rows(
        "daily_damage_rate_by_category",
        ["report_date", "item_category", "scan_count", "damage_count", "damage_rate"],
        rows,
    )
    return dg.MaterializeResult(
        metadata={"report_date": report_date, "categories_reported": len(rows), "rows_inserted": inserted}
    )


@dg.asset(partitions_def=daily_partitions, group_name="batch_reports")
def daily_reconciliation(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Does the lake (raw truth) agree with what streaming actually
    produced? Specifically checks for the failure mode that matters
    most: real traffic in the lake on a day streaming shows zero
    alerts — a much stronger signal of a broken streaming pipeline than
    "the two counts don't match exactly" would be, since scan counts
    and alert counts measure different things and were never expected
    to be numerically close."""
    report_date = context.partition_key
    table = lake.read_scan_events_for_date(report_date)
    lake_count = table.num_rows

    alert_count_raw = clickhouse.query_scalar(
        f"SELECT count(*) FROM alerts WHERE toDate(detected_at) = '{report_date}'"
    )
    alert_count = int(alert_count_raw) if alert_count_raw else 0

    lake_has_traffic_but_no_alerts = 1 if (lake_count > 0 and alert_count == 0) else 0

    inserted = clickhouse.insert_rows(
        "daily_reconciliation",
        ["report_date", "lake_event_count", "streaming_alert_count", "lake_has_traffic_but_no_alerts"],
        [
            {
                "report_date": report_date,
                "lake_event_count": lake_count,
                "streaming_alert_count": alert_count,
                "lake_has_traffic_but_no_alerts": lake_has_traffic_but_no_alerts,
            }
        ],
    )
    if lake_has_traffic_but_no_alerts:
        context.log.warning(
            "day %s has %d raw scan events but zero streaming alerts — possible streaming pipeline gap",
            report_date,
            lake_count,
        )
    return dg.MaterializeResult(
        metadata={
            "report_date": report_date,
            "lake_event_count": lake_count,
            "streaming_alert_count": alert_count,
            "flagged": bool(lake_has_traffic_but_no_alerts),
            "rows_inserted": inserted,
        }
    )
