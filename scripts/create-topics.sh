#!/usr/bin/env bash
# Run inside the kafka-topic-init container (see docker-compose.yml).
# Idempotent: --if-not-exists means re-running docker compose up is safe.
set -euo pipefail

BROKER="kafka:19092"
CREATE="/opt/kafka/bin/kafka-topics.sh --bootstrap-server $BROKER --create --if-not-exists"
RETENTION_MS=$((7 * 24 * 60 * 60 * 1000))  # 7 days

$CREATE --topic scan-events --partitions 6 --replication-factor 1 \
  --config retention.ms=$RETENTION_MS

$CREATE --topic alerts --partitions 6 --replication-factor 1 \
  --config retention.ms=$RETENTION_MS

echo "topics ready: scan-events, alerts"
