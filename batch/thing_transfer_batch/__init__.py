import dagster as dg

from .assets import daily_damage_rate_by_category, daily_reconciliation, daily_station_throughput

all_assets = [daily_station_throughput, daily_damage_rate_by_category, daily_reconciliation]

daily_batch_job = dg.define_asset_job("daily_batch_job", selection=all_assets)

# Runs shortly after midnight UTC for the day that just ended — the
# lake writer's partitions are keyed by scanned_at (event time), so by
# 00:30 the previous UTC day's data is realistically settled (a small
# buffer for last-minute late-arriving events, not a hard guarantee).
#
# default_status=RUNNING: a schedule is STOPPED by default even with
# the daemon running — someone has to explicitly start it (via the UI,
# or here) or it silently never fires. This one should always be on;
# there's no manual-approval reason to gate it behind a UI toggle.
daily_batch_schedule = dg.build_schedule_from_partitioned_job(
    daily_batch_job, hour_of_day=0, minute_of_hour=30, default_status=dg.DefaultScheduleStatus.RUNNING
)

defs = dg.Definitions(
    assets=all_assets,
    jobs=[daily_batch_job],
    schedules=[daily_batch_schedule],
)
