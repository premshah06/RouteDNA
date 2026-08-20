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

## Layout

```
proto/                  protobuf schema source of truth (buf-managed)
gen/python/              generated Python stubs (gitignored, regenerate with codegen.sh)
services/ingestion/       gRPC server: receives ScanEvents, publishes to Kafka, returns RoutingInstructions
services/station_sim/     gRPC client: simulates a scan station
docker-compose.yml         local Kafka (KRaft mode, single broker)
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/codegen.sh   # regenerates gen/python/ from proto/
docker compose up -d   # starts Kafka and creates the scan-events topic
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
