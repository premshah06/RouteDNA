"""Checkpoint 6: warehouse ingestion.

Consumes the alerts Kafka topic and loads decoded rows into
ClickHouse's `alerts` table (see warehouse/init/01_alerts.sql) for fast
dashboard queries — this is the "aggregated metrics to a warehouse"
half of Checkpoint 6, complementing lake_writer's raw-event Parquet
archive.

Why a Python loader instead of ClickHouse's own Kafka table engine
(the more idiomatic ClickHouse-native approach): the alerts topic
carries base64-encoded protobuf (see
stream_processing/jobs/stuck_package_detector.py's docstring for why —
PyFlink's Kafka connector has no raw-bytes deserialization schema
without custom Java). ClickHouse has base64Decode() but no SQL-level
protobuf decoder; its Protobuf format operates at the Kafka-engine
message-framing level, which needs raw protobuf bytes on the wire, not
an already-decoded string. Rather than force a topic-format change
that would ripple through every existing consumer (both Flink jobs,
their tests), this loader does the exact decode step Python already
has libraries for and INSERTs clean rows.
"""

import asyncio
import base64
import logging
import os
import sys

import httpx
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gen", "python"))

from packagepb.v1 import alert_pb2, common_pb2, scan_event_pb2  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("clickhouse_loader")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "thing-transfer-local")
TOPIC = "alerts"
CONSUMER_GROUP = "clickhouse-loader"

# Batch inserts rather than one HTTP round-trip per alert — ClickHouse
# is explicitly optimized for batched writes and penalizes very small,
# frequent inserts (each one creates a new part that background merges
# then have to consolidate).
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", 100))
BATCH_TIMEOUT_S = float(os.environ.get("BATCH_TIMEOUT_S", 5.0))


def _resolve_station(alert: alert_pb2.Alert) -> int:
    """The top-level Alert.station field is deliberately left UNSPECIFIED
    for multi-station alert types (see alert.proto's comment on that
    field) — a MisroutingDetail alert's "station" only makes sense as
    the actual_station it deviated to, which lives in the oneof detail,
    not the top-level field. Fall back to that instead of reporting
    every misrouting alert as station-less in the warehouse."""
    if alert.alert_type == alert_pb2.ALERT_TYPE_MISROUTING:
        return alert.misrouting_detail.actual_station
    return alert.station


def decode_alert_row(raw_value: bytes) -> dict:
    """base64 text -> Alert proto -> flat dict matching alerts table columns.

    Alert.detail is a proto3 oneof — WhichOneof tells us which of
    stuck_detail/damage_detail/misrouting_detail (if any) is actually
    populated, so only that branch's columns get real values; the
    others stay at the table's own DEFAULTs (0 / '' / []), same as an
    alert with no detail at all (shouldn't happen in practice, but
    proto3 makes "no oneof set" a valid wire state)."""
    alert = alert_pb2.Alert.FromString(base64.b64decode(raw_value))
    row = {
        "alert_id": alert.alert_id,
        "package_id": alert.package_id,
        "alert_type": alert_pb2.AlertType.Name(alert.alert_type),
        "severity": alert_pb2.Severity.Name(alert.severity),
        "station": common_pb2.StationType.Name(_resolve_station(alert)),
        "message": alert.message,
        "detected_at": alert.detected_at.ToMilliseconds() / 1000.0,
        "stuck_duration_seconds": 0,
        "threshold_seconds": 0,
        "expected_station": "",
        "actual_station": "",
        "path_so_far": [],
        "damage_type": "",
        "damage_confidence": 0.0,
    }

    which = alert.WhichOneof("detail")
    if which == "stuck_detail":
        row["stuck_duration_seconds"] = alert.stuck_detail.stuck_duration_seconds
        row["threshold_seconds"] = alert.stuck_detail.threshold_seconds
    elif which == "misrouting_detail":
        row["expected_station"] = common_pb2.StationType.Name(alert.misrouting_detail.expected_station)
        row["actual_station"] = common_pb2.StationType.Name(alert.misrouting_detail.actual_station)
        row["path_so_far"] = [common_pb2.StationType.Name(s) for s in alert.misrouting_detail.path_so_far]
    elif which == "damage_detail":
        row["damage_type"] = scan_event_pb2.DamageType.Name(alert.damage_detail.damage_type)
        row["damage_confidence"] = alert.damage_detail.confidence

    return row


def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def _esc_array(values: list) -> str:
    # ClickHouse's TabSeparated array literal: [elem,elem,...], each
    # element quoted, with the same backslash escaping as any other
    # string plus the array-literal's own special characters.
    def esc_elem(v):
        return str(v).replace("\\", "\\\\").replace("'", "\\'")

    return "[" + ",".join(f"'{esc_elem(v)}'" for v in values) + "]"


def rows_to_tsv(rows: list) -> str:
    """ClickHouse's TabSeparated insert format. Values are tab-escaped
    (no tabs/newlines in our string fields, but escaping raw \\ and
    the delimiters themselves is still correct practice for any string
    that could contain them, e.g. a message with embedded content)."""
    lines = []
    for row in rows:
        lines.append(
            "\t".join(
                [
                    _esc(row["alert_id"]),
                    _esc(row["package_id"]),
                    _esc(row["alert_type"]),
                    _esc(row["severity"]),
                    _esc(row["station"]),
                    _esc(row["message"]),
                    f"{row['detected_at']:.3f}",
                    str(row["stuck_duration_seconds"]),
                    str(row["threshold_seconds"]),
                    _esc(row["expected_station"]),
                    _esc(row["actual_station"]),
                    _esc_array(row["path_so_far"]),
                    _esc(row["damage_type"]),
                    f"{row['damage_confidence']:.4f}",
                ]
            )
        )
    return "\n".join(lines) + "\n"


async def insert_batch(client: httpx.AsyncClient, rows: list) -> None:
    if not rows:
        return
    query = (
        "INSERT INTO alerts "
        "(alert_id, package_id, alert_type, severity, station, message, detected_at, "
        "stuck_duration_seconds, threshold_seconds, expected_station, actual_station, "
        "path_so_far, damage_type, damage_confidence) "
        "FORMAT TabSeparated"
    )
    resp = await client.post(
        CLICKHOUSE_URL,
        params={"query": query},
        content=rows_to_tsv(rows),
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
    )
    resp.raise_for_status()
    logger.info("inserted %d rows into clickhouse", len(rows))


async def run() -> None:
    # enable_auto_commit=False: offsets are committed explicitly, only
    # after insert_batch() has actually returned success. aiokafka's
    # auto-commit runs on its own background timer independent of
    # whether a batch has been flushed — with it enabled, a crash (or
    # ClickHouse being briefly unreachable) between a message being
    # consumed and its batch being inserted can leave that message's
    # offset already committed, silently dropping it forever with no
    # re-delivery on restart. Manual commit-after-flush makes this
    # at-least-once instead.
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=CONSUMER_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("consuming %s from %s", TOPIC, KAFKA_BOOTSTRAP)

    async with httpx.AsyncClient(timeout=10.0) as client:
        batch: list = []
        try:
            while True:
                timed_out = False
                try:
                    msg = await asyncio.wait_for(consumer.getone(), timeout=BATCH_TIMEOUT_S)
                    try:
                        batch.append(decode_alert_row(msg.value))
                    except Exception:
                        # Decode failures are skipped (not retried) —
                        # a malformed message will never decode
                        # differently on retry. Still commits past it
                        # (via the batch flush below) since there's
                        # nothing to be gained by blocking the whole
                        # partition on one bad message.
                        logger.exception("failed to decode alert, skipping: offset=%s", msg.offset)
                except asyncio.TimeoutError:
                    timed_out = True  # batch timeout elapsed; flush whatever we have

                if batch and (len(batch) >= BATCH_SIZE or timed_out):
                    try:
                        await insert_batch(client, batch)
                    except Exception:
                        # Don't commit past a batch that failed to
                        # insert — leave the offset where it is so
                        # these messages are re-consumed and retried
                        # after a restart, rather than silently lost.
                        logger.exception("failed to insert batch into clickhouse, will retry on restart")
                        raise
                    batch = []
                    await consumer.commit()
        finally:
            if batch:
                try:
                    await insert_batch(client, batch)
                    await consumer.commit()
                except Exception:
                    logger.exception("failed to flush final batch on shutdown")
            await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())
