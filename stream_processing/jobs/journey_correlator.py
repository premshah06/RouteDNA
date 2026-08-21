"""Checkpoint 5: journey correlation.

The hardest data-engineering piece in this platform: stitch each
package's full journey (ordered sequence of station visits) from
scan-events, which arrive per-package across time and are not
guaranteed to arrive in scan order (network jitter, retries, multiple
partitions racing). Once a journey is reconstructed, compare it against
the expected topology and emit a MisroutingDetail Alert if it deviates
(station skipped, visited out of order, or the journey never reached
Dispatch).

WINDOWING STRATEGY — session windows, not fixed/sliding:
A package's journey has no fixed duration. It's bounded by inactivity —
the same shape as a user session, not a time-of-day bucket. A
KeyedProcessFunction with manual timers (Checkpoint 4's approach) would
also work here, but Flink's built-in EventTimeSessionWindows already
IS this exact abstraction (accumulate elements per key until a gap
elapses, then hand the whole accumulated group to one function call) —
reimplementing it by hand would just be a worse copy of what the
windowing API already provides. The session gap
(SESSION_GAP_MS, default 20 min) is deliberately larger than Checkpoint
4's stuck threshold (10 min): a package that's merely stuck already gets
alerted by that job, so this window's gap only needs to be "generous
enough that a real journey has almost certainly finished," not tuned to
catch stalls (that's not this job's concern).

LATE-ARRIVAL / OUT-OF-ORDER HANDLING:
Two layers, matching the two distinct kinds of "late" this system has
to tolerate:

1. Bounded out-of-orderness (MAX_OUT_OF_ORDERNESS_MS, same as
   Checkpoint 4): ordinary network jitter between a scan happening and
   it reaching Kafka. The watermark trails behind the max seen event
   time by this amount, so an event arriving up to this far "in the
   past" relative to other events on the same key still gets included
   in the right session before the window is considered closeable.

2. allowed_lateness (ALLOWED_LATENESS_MS): a SEPARATE, larger safety
   margin for events that arrive after the watermark has already
   closed the session. Rather than dropping these (which would silently
   corrupt a journey — e.g. missing the Dispatch scan and wrongly
   flagging a completed delivery as misrouted), Flink re-fires the
   window function with the merged, corrected element set, emitting an
   updated Alert with the same alert_id. This trades a small amount of
   downstream complexity (a MisroutingDetail alert can be updated after
   first being emitted) for correctness: a package's journey should
   never be judged on incomplete data if the true scan simply arrived
   late.

Events arriving even later than allowed_lateness are routed to a side
output (LATE_EVENTS_TAG) rather than silently dropped — visibility into
truly-too-late data instead of a black hole, even though no consumer
reads that side output yet.

Wire encoding: same base64-over-SimpleStringSchema convention as
Checkpoint 4 (see stuck_package_detector.py's docstring for why).

KNOWN GAPS:
1. The core mechanism (session windowing, out-of-order sorting via
build_misrouting_alert, misrouting detection) was verified live
end-to-end against the real cluster for two specific journey shapes: a
clean 4-station journey (correctly produces no alert) and a journey
that skips one station (correctly produces an alert with accurate
expected/actual stations and path_so_far). That is not exhaustive
coverage of every path shape live — a real bug involving a trailing
duplicate scan after Dispatch was caught by unit tests, not the live
run (see test_trailing_duplicate_scan_after_dispatch_does_not_alert),
which is why unit tests exist independent of live verification rather
than as a formality.
2. The allowed_lateness re-fire path specifically (a late-arriving
event correcting an already-closed session) has NOT been
verified live: a test attempting to force this exercised a watermark
that stopped advancing partway through a controlled event-time-offset
test, not yet root-caused (config/API usage per Flink's docs appears
correct; whether this is a PyFlink quirk akin to Checkpoint 4's
with_timestamp_assigner bug, or a test-harness timing issue, is
unresolved). The allowed_lateness/side_output_late_data wiring itself
matches Flink's documented WindowedStream API. Revisit if this becomes
a practical problem — e.g. during Checkpoint 6 replaying real historical
data, where late arrivals are far more likely to occur naturally.
"""

import base64
import logging
import os
import sys

from pyflink.common import Duration, Time, Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    KafkaOffsetsInitializer,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)
from pyflink.datastream.functions import ProcessWindowFunction
from pyflink.datastream.output_tag import OutputTag
from pyflink.datastream.window import EventTimeSessionWindows

sys.path.insert(0, "/opt/flink/usrlib/gen/python")

from packagepb.v1 import alert_pb2, common_pb2, scan_event_pb2  # noqa: E402

logger = logging.getLogger("journey_correlator")

SOURCE_TOPIC = "scan-events"
SINK_TOPIC = "alerts"
KAFKA_BOOTSTRAP = "kafka:19092"

MAX_OUT_OF_ORDERNESS_MS = 30 * 1000
# Larger than Checkpoint 4's 10-minute stuck threshold on purpose — see
# module docstring: this gap only needs to comfortably outlast a real
# journey, not detect stalls (that's stuck_package_detector.py's job).
SESSION_GAP_MS = int(os.environ.get("SESSION_GAP_MS", 20 * 60 * 1000))
ALLOWED_LATENESS_MS = int(os.environ.get("ALLOWED_LATENESS_MS", 5 * 60 * 1000))

# Fixed happy-path topology, matching services/ingestion/server.py's
# route_for(). Real destination-aware misrouting (checking against
# Package.destination_facility_code) needs a Package stream that
# doesn't exist yet — deferred to Checkpoint 6, where Package data
# actually gets persisted/published. This job checks structural
# correctness only: was every station visited, in the right order, with
# no skips, ending at Dispatch.
EXPECTED_PATH = [
    common_pb2.STATION_TYPE_INTAKE,
    common_pb2.STATION_TYPE_SORT_A,
    common_pb2.STATION_TYPE_SORT_B,
    common_pb2.STATION_TYPE_DISPATCH,
]

LATE_EVENTS_TAG = OutputTag("late-scan-events", Types.STRING())


def decode_scan_event(b64_line: str) -> scan_event_pb2.ScanEvent:
    return scan_event_pb2.ScanEvent.FromString(base64.b64decode(b64_line))


def encode_alert(alert: alert_pb2.Alert) -> str:
    return base64.b64encode(alert.SerializeToString()).decode("ascii")


def extract_package_id(b64_line: str) -> str:
    return decode_scan_event(b64_line).package_id


class ScanEventTimestampAssigner(TimestampAssigner):
    """Same contract requirement as Checkpoint 4's version: must be a
    TimestampAssigner instance, not a bare function — see
    stuck_package_detector.py for what goes wrong with a bare function."""

    def extract_timestamp(self, b64_line: str, record_timestamp: int) -> int:
        return decode_scan_event(b64_line).scanned_at.ToMilliseconds()


def _find_first_deviation(path: list) -> int:
    """Returns the index in `path` where it first diverges from
    EXPECTED_PATH, or -1 if path is a valid prefix of EXPECTED_PATH.

    Once Dispatch (EXPECTED_PATH's last stop) has been reached, the
    journey is complete — any further scans after that point (a scanner
    double-tap, a retry, a re-weigh at the dock) are not a "deviation."
    Judging purely on path[-1] or trailing extra entries wrongly flagged
    a legitimately completed journey as CRITICAL misrouting whenever a
    duplicate/trailing scan landed in the same session; this function
    now stops comparing as soon as Dispatch is seen, regardless of what
    (if anything) arrives after it in the same session.
    """
    dispatch_idx = len(EXPECTED_PATH) - 1
    for i, station in enumerate(path):
        if i > dispatch_idx:
            # Already matched the full expected path (including
            # Dispatch) as a prefix — trailing entries don't count.
            return -1
        if station != EXPECTED_PATH[i]:
            return i
    return -1


def build_misrouting_alert(package_id: str, b64_events) -> "alert_pb2.Alert | None":
    """Pure decision logic, factored out of JourneyCorrelator.process so
    it's directly unit-testable without faking Flink's window Context.
    Sorts the session's accumulated events by event time, reconstructs
    the path, and returns a MisroutingDetail Alert if the path deviates
    from EXPECTED_PATH or never reaches Dispatch — or None if the
    journey is clean."""
    events = sorted(
        (decode_scan_event(line) for line in b64_events),
        key=lambda e: e.scanned_at.ToMilliseconds(),
    )
    path = [e.station for e in events]

    if not path:
        # Shouldn't happen in practice — a session window can't fire
        # with zero elements — but there is genuinely nothing to judge
        # a misrouting verdict on with no scans at all.
        return None

    deviation_index = _find_first_deviation(path)
    # Dispatch reached anywhere in the path, not just as the last
    # element — a trailing extra/duplicate scan after Dispatch must not
    # make an otherwise-complete journey look unfinished.
    reached_dispatch = common_pb2.STATION_TYPE_DISPATCH in path
    is_misrouted = deviation_index != -1 or not reached_dispatch

    if not is_misrouted:
        return None

    expected_station = (
        EXPECTED_PATH[deviation_index]
        if deviation_index != -1 and deviation_index < len(EXPECTED_PATH)
        else common_pb2.STATION_TYPE_DISPATCH
    )
    actual_station = path[deviation_index] if deviation_index != -1 else path[-1]

    alert = alert_pb2.Alert(
        # Stable alert_id (not timestamp-suffixed like Checkpoint 4's
        # stuck alerts) so a late-arriving event that re-fires this
        # window (see allowed_lateness in the module docstring) UPDATES
        # the same alert rather than creating a duplicate.
        alert_id=f"misrouting-{package_id}",
        package_id=package_id,
        alert_type=alert_pb2.ALERT_TYPE_MISROUTING,
        severity=alert_pb2.SEVERITY_CRITICAL if not reached_dispatch else alert_pb2.SEVERITY_WARNING,
        message=(
            f"Package journey diverged from expected path: expected "
            f"{common_pb2.StationType.Name(expected_station)}, "
            f"observed path ends at {common_pb2.StationType.Name(actual_station)}"
        ),
    )
    alert.misrouting_detail.expected_station = expected_station
    alert.misrouting_detail.actual_station = actual_station
    alert.misrouting_detail.path_so_far.extend(path)
    # Last event's own scan time, not wall-clock now() — this function
    # doesn't have access to the window's fire timestamp, and the last
    # scan in the (sorted) path is the most meaningful "when this
    # journey's outcome became knowable" for this alert. Left unset,
    # this field silently defaults to protobuf's epoch-zero Timestamp.
    alert.detected_at.FromMilliseconds(events[-1].scanned_at.ToMilliseconds())
    return alert


class JourneyCorrelator(ProcessWindowFunction):
    def process(self, package_id: str, context: "ProcessWindowFunction.Context", elements):
        alert = build_misrouting_alert(package_id, elements)
        if alert is not None:
            yield encode_alert(alert)


def build_job(env: StreamExecutionEnvironment):
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP)
        .set_topics(SOURCE_TOPIC)
        .set_group_id("journey-correlator")
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    watermark_strategy = (
        WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_millis(MAX_OUT_OF_ORDERNESS_MS))
        .with_timestamp_assigner(ScanEventTimestampAssigner())
        .with_idleness(Duration.of_millis(60 * 1000))
    )

    scan_events = env.from_source(source, watermark_strategy, "scan-events-source-journey")

    windowed = (
        scan_events.key_by(extract_package_id, key_type=Types.STRING())
        .window(EventTimeSessionWindows.with_gap(Time.milliseconds(SESSION_GAP_MS)))
        .allowed_lateness(ALLOWED_LATENESS_MS)
        .side_output_late_data(LATE_EVENTS_TAG)
    )

    alerts = windowed.process(JourneyCorrelator(), output_type=Types.STRING())

    # No consumer reads this yet — routed to a side output rather than
    # silently dropped purely for visibility (see module docstring).
    # print_sink is the trivial connector for "make this observable in
    # the TaskManager log" without inventing a MapFunction whose only
    # job is a log call.
    late_events = alerts.get_side_output(LATE_EVENTS_TAG)
    late_events.print()

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
    env.add_python_file("/opt/flink/usrlib/gen/python")
    build_job(env)
    env.execute("journey-correlator")
