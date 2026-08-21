-- Hourly alert counts by type/severity/station, kept up to date
-- automatically as rows land in `alerts` — no separate rollup job to
-- schedule or forget to run. AggregatingMergeTree + a materialized
-- view is the idiomatic ClickHouse pattern for "pre-aggregate on
-- write, read cheap" instead of aggregating raw rows on every
-- dashboard query.
CREATE TABLE IF NOT EXISTS alert_hourly_rollup
(
    hour DateTime,
    alert_type LowCardinality(String),
    severity LowCardinality(String),
    station LowCardinality(String),
    alert_count AggregateFunction(count)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMMDD(hour)
ORDER BY (hour, alert_type, severity, station);

CREATE MATERIALIZED VIEW IF NOT EXISTS alert_hourly_rollup_mv
TO alert_hourly_rollup
AS
SELECT
    toStartOfHour(detected_at) AS hour,
    alert_type,
    severity,
    station,
    countState() AS alert_count
FROM alerts
GROUP BY hour, alert_type, severity, station;

-- Query pattern for a dashboard reading this rollup:
--   SELECT hour, alert_type, countMerge(alert_count) AS alerts
--   FROM alert_hourly_rollup
--   WHERE hour >= now() - INTERVAL 24 HOUR
--   GROUP BY hour, alert_type
--   ORDER BY hour;
