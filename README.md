# Smart Package Routing & Damage Detection Platform

Packages move through facility checkpoints (Intake -> Sort A -> Sort B ->
Dispatch). Each station streams scan events over gRPC into a backend
pipeline; the platform detects damage, stuck packages, and misrouting
before they become customer-facing failures.

## Status

- **Checkpoint 1** (done): protobuf schema contracts — `proto/packagepb/v1/`.
- **Checkpoint 2** (done): one simulated scan station + ingestion service,
  gRPC bidirectional streaming only, no Kafka/storage yet.
- **Checkpoint 3** (done): ingestion service publishes validated ScanEvents
  to Kafka (`scan-events` topic, keyed by `package_id`), decoupled from the
  gRPC routing response. Local Kafka via `docker-compose.yml`.
- **Checkpoint 4** (done): PyFlink job (`stream_processing/jobs/stuck_package_detector.py`)
  flags packages with no scan for 10+ minutes, publishing `Alert` protos to
  a new `alerts` topic. Local Flink cluster (JobManager + TaskManager) via
  `docker-compose.yml`. Job submission is a manual step for now — see below.

## Architecture

Hand-drawn pipeline diagram (open `docs/architecture.html` in a browser):
current gRPC + Kafka flow, plus what's designed but not yet built.
Published copy: https://claude.ai/code/artifact/42406ee7-f0b6-4949-8870-116059d91b76

## Layout

```
proto/                       protobuf schema source of truth (buf-managed)
gen/python/                   generated Python stubs (gitignored, regenerate with codegen.sh)
services/ingestion/            gRPC server: receives ScanEvents, publishes to Kafka, returns RoutingInstructions
services/station_sim/          gRPC client: simulates a scan station
stream_processing/jobs/         PyFlink jobs (stuck-package detection, journey correlation)
stream_processing/flink_image/   Dockerfile: Flink + PyFlink + Kafka connector
docker-compose.yml               local Kafka (KRaft) + Flink cluster
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/codegen.sh   # regenerates gen/python/ from proto/
docker compose up -d   # starts Kafka, creates topics, starts the Flink cluster
```

**PyFlink is Docker-only** — it needs a JVM and isn't installed in the
local venv. Job code lives in `stream_processing/jobs/` but only runs
inside the `thing-transfer-flink` image (built automatically by
`docker compose up`).

## Submitting the stuck-package detector

`docker compose up` starts an empty Flink cluster — the job itself is a
manual submission step for now (auto-submission via a one-shot container
hit a Flink CLI/RPC hang not worth blocking on; see git history for the
investigation):

```bash
docker compose exec flink-jobmanager \
  /opt/flink/bin/flink run -d -py /opt/flink/usrlib/jobs/stuck_package_detector.py
```

Check it's running: `docker compose exec flink-jobmanager /opt/flink/bin/flink list`
Flink Web UI: http://localhost:8081

Override thresholds for faster local testing (defaults: 10 min stuck
threshold, 60s idle-partition timeout):

```bash
docker compose exec -e STUCK_THRESHOLD_MS=15000 -e IDLE_PARTITION_TIMEOUT_MS=10000 \
  flink-jobmanager /opt/flink/bin/flink run -d -py /opt/flink/usrlib/jobs/stuck_package_detector.py
```

## Running the Checkpoint 3 demo

Terminal 1 — start the ingestion service:

```bash
source .venv/bin/activate
PYTHONPATH=gen/python:services/ingestion:services/common python3 services/ingestion/server.py
```

Terminal 2 — run a simulated station against it:

```bash
source .venv/bin/activate
PYTHONPATH=gen/python:services/station_sim:services/common python3 services/station_sim/simulator.py \
  --station intake --num-packages 5 --count 20 --interval 0.5
```

You'll see scan events sent by the station and routing instructions
returned by the ingestion service on the same stream, correlated by
`event_id`. Each valid event is also published to Kafka's `scan-events`
topic as a side effect — check it landed with:

```bash
docker exec thing-transfer-kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --broker-list localhost:9092 --topic scan-events
```

## Tests

```bash
source .venv/bin/activate
python3 -m pytest services/ingestion/tests/ -v         # fast suite, no Docker needed (fake Kafka producer)
python3 -m pytest services/ingestion/tests/ -v -m kafka # requires: docker compose up -d
```

The fast suite includes pure unit tests of the routing decision logic and
end-to-end streaming tests (real `grpc.aio` server/client pair on an
ephemeral port, fake in-memory Kafka producer). `test_kafka_integration.py`
is marked `kafka` and excluded by default; it exercises the real broker —
produce via gRPC, consume back, decode, and verify.

Flink job tests (needs pyflink, which only exists inside the Docker
image — see `scripts/run_flink_tests.sh`):

```bash
./scripts/run_flink_tests.sh
```

## Reading alerts

```bash
docker exec thing-transfer-kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic alerts --from-beginning
```

Values are base64-encoded `Alert` protos (see
`services/ingestion/kafka_producer.py` docstring for why) — decode with:

```python
import base64, sys
sys.path.insert(0, "gen/python")
from packagepb.v1 import alert_pb2
alert_pb2.Alert.FromString(base64.b64decode(line))
```
