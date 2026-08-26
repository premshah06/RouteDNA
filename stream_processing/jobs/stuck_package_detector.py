"""Checkpoint 4: stuck-package detection.

The simplest real anomaly this platform catches: a package that was
scanned at some station and then never scanned again within a threshold
window. Deliberately built and proven before the harder journey
correlation problem (Checkpoint 5) — this job only needs to track "when
was this package's last scan," not reconstruct its whole path.

Design: a KeyedProcessFunction keyed by package_id, using EVENT-TIME
timers (not wall-clock polling). On every scan:
  1. cancel any previously-registered timer for this package (the
     package moved, it's not stuck)
  2. remember the last-scan timestamp and station in keyed state
  3. register a new timer at last_scan_time + STUCK_THRESHOLD

If the timer fires without being cancelled first, no newer scan arrived
in time — emit a StuckDetail Alert for that package/station.

Event time (not processing time) is used so detection is driven by
watermarks derived from the data itself, not wall-clock speed. This
matters once this job runs against replayed/backfilled history at
non-real-time speed (Checkpoint 6+), and it's also what keeps this job's
timing semantics consistent with the interval-join approach Checkpoint 5
will need for out-of-order journey correlation — same event-time
foundation, harder join on top.

Wire encoding: PyFlink 1.19's DataStream Kafka connector has no built-in
raw-byte-array (de)serialization schema without writing custom Java, so
both scan-events and alerts topics carry base64-encoded protobuf as
UTF-8 strings, read/written with the connector's native
SimpleStringSchema. See services/ingestion/kafka_producer.py for the
producer-side half of this convention.
"""

import base64
import logging
import os
import sys

from pyflink.common import Duration, Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    KafkaOffsetsInitializer,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)
from pyflink.datastream.functions import KeyedProcessFunction, RuntimeContext
from pyflink.datastream.state import ValueStateDescriptor

sys.path.insert(0, "/opt/flink/usrlib/gen/python")
sys.path.insert(0, "/opt/flink/usrlib/services/common")

from packagepb.v1 import alert_pb2, common_pb2, scan_event_pb2  # noqa: E402
from thresholds import STUCK_THRESHOLD_MS  # noqa: E402

logger = logging.getLogger("stuck_package_detector")

SOURCE_TOPIC = "scan-events"
SINK_TOPIC = "alerts"
KAFKA_BOOTSTRAP = "kafka:19092"  # in-network hostname, not localhost:9092
MAX_OUT_OF_ORDERNESS_MS = 30 * 1000  # tolerate scans arriving up to 30s late
# How long a Kafka partition can go quiet before it's excluded from the
# watermark-minimum calculation (see with_idleness usage below).
IDLE_PARTITION_TIMEOUT_MS = int(os.environ.get("IDLE_PARTITION_TIMEOUT_MS", 60 * 1000))


def decode_scan_event(b64_line: str) -> scan_event_pb2.ScanEvent:
    return scan_event_pb2.ScanEvent.FromString(base64.b64decode(b64_line))


def encode_alert(alert: alert_pb2.Alert) -> str:
    return base64.b64encode(alert.SerializeToString()).decode("ascii")


def build_stuck_alert(package_id: str, last_station: int, last_scan_time: int, timer_fire_time: int) -> alert_pb2.Alert:
    """Pure alert-construction logic, factored out of on_timer so it's
    directly unit-testable without faking Flink's OnTimerContext."""
    threshold_seconds = STUCK_THRESHOLD_MS // 1000
    threshold_display = (
        f"{threshold_seconds // 60}+ minutes" if threshold_seconds >= 60 else f"{threshold_seconds}+ seconds"
    )
    alert = alert_pb2.Alert(
        alert_id=f"stuck-{package_id}-{timer_fire_time}",
        package_id=package_id,
        alert_type=alert_pb2.ALERT_TYPE_STUCK_PACKAGE,
        severity=alert_pb2.SEVERITY_WARNING,
        message=(
            f"Package stuck at {common_pb2.StationType.Name(last_station)} for "
            f"{threshold_display} with no further scan"
        ),
        station=last_station,
    )
    # timer_fire_time is the timer's fire time (event time) — when this
    # anomaly was actually detected, not wall-clock now(). Left unset,
    # this field defaults to protobuf's epoch-zero Timestamp, which is
    # silent and easy to miss until something (e.g. a warehouse
    # partitioned by this field) actually reads it.
    alert.detected_at.FromMilliseconds(timer_fire_time)
    alert.stuck_detail.last_scan_at.FromMilliseconds(last_scan_time)
    # timer_fire_time is >= last_scan_time + threshold, not necessarily
    # equal to it — watermark lag between when the timer fires and how
    # far event time has actually advanced can push the true elapsed
    # duration past the configured threshold.
    alert.stuck_detail.stuck_duration_seconds = (timer_fire_time - last_scan_time) // 1000
    alert.stuck_detail.threshold_seconds = threshold_seconds
    return alert


class StuckPackageDetector(KeyedProcessFunction):
    """Per-package_id: track last scan time/station, fire an Alert if no
    newer scan arrives before last_scan_time + STUCK_THRESHOLD_MS."""

    def open(self, runtime_context: RuntimeContext):
        self.last_scan_time = runtime_context.get_state(
            ValueStateDescriptor("last_scan_time", Types.LONG())
        )
        self.last_station = runtime_context.get_state(
            ValueStateDescriptor("last_station", Types.INT())
        )
        self.active_timer = runtime_context.get_state(
            ValueStateDescriptor("active_timer", Types.LONG())
        )

    def process_element(self, b64_line: str, ctx: "KeyedProcessFunction.Context"):
        event = decode_scan_event(b64_line)
        event_time = ctx.timestamp()

        existing_timer = self.active_timer.value()
        if existing_timer is not None:
            ctx.timer_service().delete_event_time_timer(existing_timer)

        self.last_scan_time.update(event_time)
        self.last_station.update(event.station)

        fire_at = event_time + STUCK_THRESHOLD_MS
        ctx.timer_service().register_event_time_timer(fire_at)
        self.active_timer.update(fire_at)
        return iter(())

    def on_timer(self, timestamp: int, ctx: "KeyedProcessFunction.OnTimerContext"):
        # Timer fired and was never cancelled by a newer scan -> stuck.
        self.active_timer.clear()

        last_scan_time = self.last_scan_time.value()
        last_station = self.last_station.value()
        if last_scan_time is None:
            return  # defensive: state was cleared/never set

        alert = build_stuck_alert(ctx.get_current_key(), last_station, last_scan_time, timestamp)
        yield encode_alert(alert)


def extract_package_id(b64_line: str) -> str:
    return decode_scan_event(b64_line).package_id


class ScanEventTimestampAssigner(TimestampAssigner):
    """WatermarkStrategy.with_timestamp_assigner requires an object
    implementing this interface (extract_timestamp), not a bare
    function — passing a plain function type-checks in some code paths
    but is not the documented contract and produced silently-wrong
    watermarks in practice (timers registered but never firing)."""

    def extract_timestamp(self, b64_line: str, record_timestamp: int) -> int:
        return decode_scan_event(b64_line).scanned_at.ToMilliseconds()


def build_job(env: StreamExecutionEnvironment):
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP)
        .set_topics(SOURCE_TOPIC)
        .set_group_id("stuck-package-detector")
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    # with_idleness matters a lot here: scan-events has 6 partitions but
    # a real facility scan rate means most partitions go quiet between
    # scans. Flink's default per-split watermark merge takes the MIN
    # across all splits/partitions, so any partition that never receives
    # traffic holds the overall watermark at -inf forever and no timer
    # ever fires anywhere, in any partition. with_idleness excludes a
    # split from that min once it's been quiet longer than the given
    # duration, letting active partitions' watermarks (and therefore
    # this job's timers) advance normally.
    watermark_strategy = (
        WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_millis(MAX_OUT_OF_ORDERNESS_MS))
        .with_timestamp_assigner(ScanEventTimestampAssigner())
        .with_idleness(Duration.of_millis(IDLE_PARTITION_TIMEOUT_MS))
    )

    scan_events = env.from_source(source, watermark_strategy, "scan-events-source")

    alerts = scan_events.key_by(extract_package_id, key_type=Types.STRING()).process(
        StuckPackageDetector(), output_type=Types.STRING()
    )

    sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic(SINK_TOPIC)
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .build()
    )

    alerts.sink_to(sink)
    return env


if __name__ == "__main__":
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)
    # process_element/on_timer run in a separate Python worker process
    # (Beam's process-based execution model) that does NOT inherit this
    # client process's sys.path — add_python_file ships the generated
    # protobuf stubs into that worker's environment explicitly. Without
    # this, imports inside StuckPackageDetector fail with
    # ModuleNotFoundError even though the same import works fine here in
    # the submitting process.
    env.add_python_file("/opt/flink/usrlib/gen/python")
    env.add_python_file("/opt/flink/usrlib/services/common")
    build_job(env)
    env.execute("stuck-package-detector")
