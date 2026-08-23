---
description: Use when writing or debugging a PyFlink DataStream job — event-time processing, KeyedProcessFunction with timers, or a job whose watermark seems stuck/frozen. Covers three silent-failure traps (bare-function TimestampAssigner, idle-partition watermark starvation, misreading "watermark stopped advancing" as a bug) and the Docker image fix PyFlink needs for pemja's native build. Reach for this before writing a new stream-processing job from scratch or when a Flink job's timers/windows aren't firing as expected.
---

# PyFlink stream-processing job template

Three of this project's PyFlink bugs were the same shape: something
*type-checks* and runs without error, but silently produces wrong
output, and only live traffic (not a unit test) revealed it. This
skill exists to skip re-discovering them.

## Trap 1: `with_timestamp_assigner` needs a class instance, not a function

```python
# WRONG — type-checks, runs, silently produces frozen/wrong watermarks
def extract_ts(event, record_timestamp):
    return event.scanned_at.ToMilliseconds()

WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(5)) \
    .with_timestamp_assigner(extract_ts)  # bug: bare function
```

```python
# CORRECT — a TimestampAssigner instance
from pyflink.common.watermark_strategy import TimestampAssigner

class ScanEventTimestampAssigner(TimestampAssigner):
    def extract_timestamp(self, event, record_timestamp):
        return event.scanned_at.ToMilliseconds()

WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(5)) \
    .with_timestamp_assigner(ScanEventTimestampAssigner())
```

A bare function passes PyFlink's type checks in some code paths but
doesn't correctly wire into the watermark generator underneath. If
event-time timers or windows aren't firing, check this first — it's a
silent failure, not an exception.

## Trap 2: idle partitions freeze the watermark for the whole job

Flink computes watermark advancement as the *minimum* across all
Kafka partition splits a task is reading. A multi-partition topic
(e.g. 6 partitions) with sparse/uneven traffic — some partitions
getting events, others not — holds the *entire* job's watermark at
whatever the quietest partition last reported, even `-inf` if that
partition has never received anything. This blocks every timer and
window in the job, not just the ones logically tied to that partition.

Fix:
```python
WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(5)) \
    .with_timestamp_assigner(MyTimestampAssigner()) \
    .with_idleness(Duration.of_seconds(30))  # <-- this
```

`with_idleness` tells Flink to exclude a partition from the watermark
minimum once it's gone quiet longer than the given duration, instead
of letting one silent partition starve the whole pipeline.

## Trap 3: "watermark stopped advancing" is very often correct behavior, not a bug

If a test scenario sends a fixed burst of events and then the
watermark visibly climbs for a bit and then *stops*, this is almost
always **not a bug** — it's Flink correctly refusing to advance the
watermark further because there's no new data to derive a later
timestamp from. A watermark can only advance based on evidence
(arriving events), and a burst that stops sending has no more evidence
to offer.

Before chasing this as a code bug: switch the test traffic pattern
from "one burst, then silence" to a continuous trickle that keeps
crossing whatever time threshold the test needs to observe (e.g. a
stuck-package timeout, a session-window gap). If the watermark then
advances correctly with trickle traffic, there was never a bug — only
a test methodology gap.

## Docker: pemja needs a JDK, not just a JRE

The official Flink Docker images ship a JRE only, at
`JAVA_HOME=/opt/java/openjdk`. PyFlink's `pemja` bridge (Python↔JVM)
needs to compile a native extension against JDK headers at
container-build time, which a JRE doesn't have.

Fix: install `openjdk-11-jdk-headless` (or whatever major version
matches the base Flink image) in the Dockerfile, then **retarget the
existing `/opt/java/openjdk` symlink** to point at the new JDK install
— don't just set a separate `JDK_HOME` env var, because other Flink
tooling in the image already hard-expects `JAVA_HOME` to resolve to
that exact path.

```dockerfile
RUN apt-get update && apt-get install -y openjdk-11-jdk-headless && \
    rm -rf /opt/java/openjdk && \
    ln -s /usr/lib/jvm/java-11-openjdk-* /opt/java/openjdk
```

## KeyedProcessFunction + event-time timer skeleton

The shape used for both stuck-package detection and journey
correlation in this project:

```python
from pyflink.datastream import KeyedProcessFunction
from pyflink.datastream.state import ValueStateDescriptor

class MyDetector(KeyedProcessFunction):
    def open(self, runtime_context):
        self.last_seen_state = runtime_context.get_state(
            ValueStateDescriptor("last_seen", Types.PICKLED_BYTE_ARRAY())
        )

    def process_element(self, event, ctx: 'KeyedProcessFunction.Context'):
        self.last_seen_state.update(event)
        # Register a timer relative to event time, not wall-clock time —
        # this is what makes the detector replay-safe against historical
        # data, not just live traffic.
        ctx.timer_service().register_event_time_timer(
            ctx.timestamp() + THRESHOLD_MS
        )

    def on_timer(self, timestamp, ctx: 'KeyedProcessFunction.OnTimerContext'):
        last = self.last_seen_state.value()
        if last is not None and last.scanned_at.ToMilliseconds() + THRESHOLD_MS <= timestamp:
            yield build_alert(last, timestamp)  # extract to a pure function — see below
```

**Extract alert-construction to a pure function** (`build_stuck_alert`,
`build_misrouting_alert`, etc.) separate from the
`KeyedProcessFunction` — this project's most subtle bug
(`Alert.detected_at` never being set, silently defaulting to epoch
zero and landing every row in ClickHouse's `19700101` partition) was
caught specifically *because* the extraction made it easy to write a
focused regression test asserting the field was set, rather than
having to stand up a full keyed-timer test harness to check one field.

## requirements.txt version pinning (apache-flink chain)

`apache-flink` depends on `apache-beam`, which caps `protobuf<4.24.0`.
If a project pulls in a newer `grpcio-tools` alongside PyFlink, expect
a resolution conflict. Working combination for this project:
`protobuf==4.23.4`, `grpcio-tools==1.59.0` (older `grpcio-tools`
needs `pkg_resources`, which was removed from `setuptools>=81`, so
also pin `setuptools<81`). Document the *chain* of forced pins in
`requirements.txt` comments, not just the pins themselves — the next
person (or the next version bump) needs to know *why* before loosening
any one of them.
