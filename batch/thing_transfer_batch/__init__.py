import dagster as dg

from .assets import daily_damage_rate_by_category, daily_reconciliation, daily_station_throughput

all_assets = [daily_station_throughput, daily_damage_rate_by_category, daily_reconciliation]

daily_batch_job = dg.define_asset_job("daily_batch_job", selection=all_assets)

# Runs shortly after midnight UTC for the day that just ended — the
# lake writer's partitions are keyed by scanned_at (event time), so by
# 00:30 the previous UTC day's data is realistically settled (a small
# buffer for last-minute late-arriving events, not a hard guarantee).
daily_batch_schedule = dg.build_schedule_from_partitioned_job(daily_batch_job, hour_of_day=0, minute_of_hour=30)

defs = dg.Definitions(
    assets=all_assets,
    jobs=[daily_batch_job],
    schedules=[daily_batch_schedule],
)
