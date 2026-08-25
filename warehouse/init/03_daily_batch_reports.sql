-- Checkpoint 8: outputs of the Dagster batch layer (batch/), which
-- reprocesses each day's raw Parquet from the lake (data/lake/scan_events/)
-- rather than reading Kafka. Two things this buys over the streaming
-- rollups in 02_alert_rollups.sql:
--   1. Metrics that need a full-day view (throughput, damage rate by
--      item category) rather than a rolling hourly window.
--   2. A reconciliation check comparing the lake's raw event count
--      against what streaming actually wrote to `alerts` — catching
--      any gap between the two paths (a crashed Flink job, a dropped
--      Kafka partition, etc.) that neither path could detect on its own.
--
-- ReplacingMergeTree(inserted_at) rather than plain MergeTree: batch
-- runs are idempotent by design (a rerun for the same day should
-- replace, not duplicate, that day's row) and Dagster jobs do get
-- rerun (backfills, retries after a failure) — ReplacingMergeTree
-- keeps the latest run's row per key without the loader needing to
-- DELETE first.
CREATE TABLE IF NOT EXISTS daily_station_throughput
(
    report_date Date,
    station LowCardinality(String),
    scan_count UInt64,
    unique_packages UInt64,
    damage_count UInt64,
    unreadable_count UInt64,
    inserted_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(inserted_at)
PARTITION BY toYYYYMM(report_date)
ORDER BY (report_date, station);

CREATE TABLE IF NOT EXISTS daily_damage_rate_by_category
(
    report_date Date,
    item_category LowCardinality(String),
    scan_count UInt64,
    damage_count UInt64,
    damage_rate Float32,
    inserted_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(inserted_at)
PARTITION BY toYYYYMM(report_date)
ORDER BY (report_date, item_category);

-- One row per day: did the lake's raw event count for that day roughly
-- match what streaming produced? A large gap means something upstream
-- of one path (not necessarily this one) silently lost data —
-- worth a human looking, which is why this is a report, not an
-- automatic fix.
CREATE TABLE IF NOT EXISTS daily_reconciliation
(
    report_date Date,
    lake_event_count UInt64,
    streaming_alert_count UInt64,
    -- Not a ratio of the two counts (they measure different things —
    -- raw scans vs. derived alerts): a simple presence check, since
    -- the real signal this table exists to catch is "streaming
    -- produced zero alerts on a day the lake shows real traffic",
    -- not a precise reconciliation between two different metrics.
    lake_has_traffic_but_no_alerts UInt8,
    inserted_at DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(inserted_at)
PARTITION BY toYYYYMM(report_date)
ORDER BY report_date;
