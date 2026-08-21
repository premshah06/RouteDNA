"""Checkpoint 6: data lake ingestion.

Consumes scan-events from Kafka and archives raw events as
Hive-partitioned Parquet under data/lake/scan_events/ — the "raw
events to a data lake" half of Checkpoint 6, complementing
warehouse/clickhouse_loader's aggregated-alerts warehouse.

Deliberately NOT a Flink job (unlike stuck_package_detector.py /
journey_correlator.py): this is pure "durably persist what already
exists," with no windowing, joins, or event-time reasoning — Flink's
stream-processing semantics buy nothing here, so a plain Python
consumer batching Kafka messages into Parquet files is the simplest
tool that's actually correct for the job (see the Checkpoint 6 scoping
discussion — this mirrors the same "don't reach for a bigger tool than
the problem needs" call made for ClickHouse ingestion).

Partition layout: date=YYYY-MM-DD/hour=HH, derived from each event's
own scanned_at (event time), not wall-clock arrival time — a late
arrival still lands in the partition matching when it was physically
scanned, so a query for "what happened during hour X" doesn't miss
events that arrived on wire slightly after X but happened during it.
"""

import asyncio
import base64
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gen", "python"))

from packagepb.v1 import common_pb2, scan_event_pb2  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("lake_writer")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC = "scan-events"
CONSUMER_GROUP = "lake-writer"

LAKE_ROOT = Path(os.environ.get("LAKE_ROOT", Path(__file__).resolve().parents[2] / "data" / "lake"))

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", 200))
BATCH_TIMEOUT_S = float(os.environ.get("BATCH_TIMEOUT_S", 10.0))

_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("package_id", pa.string()),
        ("station", pa.string()),
        ("scanner_id", pa.string()),
        ("scanned_at", pa.timestamp("ms", tz="UTC")),
        ("result", pa.string()),
        ("damage_type", pa.string()),
        ("damage_confidence", pa.float32()),
    ]
)


def decode_scan_event_row(raw_value: bytes) -> dict:
    event = scan_event_pb2.ScanEvent.FromString(base64.b64decode(raw_value))
    scanned_at = event.scanned_at.ToDatetime(tzinfo=timezone.utc)
    return {
        "event_id": event.event_id,
        "package_id": event.package_id,
        "station": common_pb2.StationType.Name(event.station),
        "scanner_id": event.scanner_id,
        "scanned_at": scanned_at,
        "result": scan_event_pb2.ScanResult.Name(event.result),
        "damage_type": (
            scan_event_pb2.DamageType.Name(event.damage_assessment.damage_type)
            if event.result == scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED
            else ""
        ),
        "damage_confidence": event.damage_assessment.confidence if event.result == scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED else 0.0,
        "_partition": (scanned_at.strftime("%Y-%m-%d"), scanned_at.strftime("%H")),
    }


def write_partition(date: str, hour: str, rows: list) -> Path:
    partition_dir = LAKE_ROOT / "scan_events" / f"date={date}" / f"hour={hour}"
    partition_dir.mkdir(parents=True, exist_ok=True)

    columns = {field.name: [row[field.name] for row in rows] for field in _SCHEMA}
    table = pa.table(columns, schema=_SCHEMA)

    # Filename includes a timestamp so repeated flushes to the same
    # partition don't collide/overwrite — each batch is its own file,
    # consistent with how streaming lake writers typically work (many
    # small files per partition, compacted later by a separate job if
    # needed — not built here, out of scope for this checkpoint).
    filename = f"batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.parquet"
    out_path = partition_dir / filename
    pq.write_table(table, out_path)
    return out_path


def flush(batch: list) -> None:
    by_partition = defaultdict(list)
    for row in batch:
        by_partition[row["_partition"]].append(row)
    for (date, hour), rows in by_partition.items():
        path = write_partition(date, hour, rows)
        logger.info("wrote %d rows to %s", len(rows), path)


async def run() -> None:
    # enable_auto_commit=False, same reasoning as
    # warehouse/clickhouse_loader/loader.py: commit only after a batch
    # is durably written, so a crash between consuming and flushing
    # can't leave already-committed offsets pointing past unwritten data.
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=CONSUMER_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("consuming %s from %s, writing to %s", TOPIC, KAFKA_BOOTSTRAP, LAKE_ROOT)

    batch: list = []
    try:
        while True:
            timed_out = False
            try:
                msg = await asyncio.wait_for(consumer.getone(), timeout=BATCH_TIMEOUT_S)
                try:
                    batch.append(decode_scan_event_row(msg.value))
                except Exception:
                    logger.exception("failed to decode scan event, skipping: offset=%s", msg.offset)
            except asyncio.TimeoutError:
                timed_out = True

            if batch and (len(batch) >= BATCH_SIZE or timed_out):
                try:
                    flush(batch)
                except Exception:
                    logger.exception("failed to write batch to lake, will retry on restart")
                    raise
                batch = []
                await consumer.commit()
    finally:
        if batch:
            try:
                flush(batch)
                await consumer.commit()
            except Exception:
                logger.exception("failed to flush final batch on shutdown")
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())
