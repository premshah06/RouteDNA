# Smart Package Routing & Damage Detection Platform

Packages move through facility checkpoints (Intake -> Sort A -> Sort B ->
Dispatch). Each station streams scan events over gRPC into a backend
pipeline; the platform detects damage, stuck packages, and misrouting
before they become customer-facing failures.

## Status

- **Checkpoint 1** (done): protobuf schema contracts — `proto/packagepb/v1/`.
- **Checkpoint 2** (done): one simulated scan station + ingestion service,
  gRPC bidirectional streaming only, no Kafka/storage yet.

## Layout

```
proto/                  protobuf schema source of truth (buf-managed)
gen/python/              generated Python stubs (gitignored, regenerate with codegen.sh)
services/ingestion/       gRPC server: receives ScanEvents, returns RoutingInstructions
services/station_sim/     gRPC client: simulates a scan station
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/codegen.sh   # regenerates gen/python/ from proto/
```

## Running the Checkpoint 2 demo

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
`event_id`.

## Tests

```bash
source .venv/bin/activate
python3 -m pytest services/ingestion/tests/ -v
```

Includes both pure unit tests of the routing decision logic and true
end-to-end tests that spin up a real `grpc.aio` server/client pair against
an ephemeral port.
