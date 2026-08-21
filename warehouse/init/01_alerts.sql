-- Raw alerts table: one row per Alert message, inserted by
-- warehouse/clickhouse_loader (a Python Kafka consumer — see that
-- module's docstring for why ClickHouse doesn't ingest this directly
-- via its own Kafka engine: protobuf-in-base64 has no SQL-level
-- decoder in ClickHouse, only a Kafka-engine-level Protobuf format
-- that operates on raw message bytes, which this platform's Flink
-- jobs cannot produce without custom Java — see
-- stream_processing/jobs/stuck_package_detector.py's docstring).
--
-- MergeTree, partitioned by day: this is fact data, append-only, and
-- queries naturally filter by a recent time range (a dashboard asking
-- "alerts in the last N hours"), which is exactly what MergeTree's
-- partition pruning is built for.
CREATE TABLE IF NOT EXISTS alerts
(
    alert_id String,
    package_id String,
    alert_type LowCardinality(String),
    severity LowCardinality(String),
    station LowCardinality(String),
    message String,
    detected_at DateTime64(3),
    inserted_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(detected_at)
ORDER BY (alert_type, detected_at)
TTL toDateTime(detected_at) + INTERVAL 90 DAY;
