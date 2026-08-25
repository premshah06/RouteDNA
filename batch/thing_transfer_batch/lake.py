"""Reads Checkpoint 6's raw Parquet lake (data/lake/scan_events/date=YYYY-MM-DD/hour=HH/*.parquet).

No PyArrow dataset/partitioning magic here on purpose: the lake writer
already encodes the partition in the directory path, and a batch run
only ever wants exactly one day, so a plain glob over that day's hour=
subdirectories is simpler and more obviously correct than wiring up a
partitioned dataset reader for a one-day slice.
"""

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds

# Defaults to the repo-root data/lake for local (non-Docker) runs, same
# convention as warehouse/lake_writer/writer.py's LAKE_ROOT — overridden
# by the container, which mounts the lake at a fixed path instead of
# relying on parents[N] resolving correctly from a different WORKDIR.
LAKE_ROOT = Path(os.environ.get("LAKE_ROOT", Path(__file__).resolve().parents[2] / "data" / "lake"))


def read_scan_events_for_date(report_date: str) -> pa.Table:
    """report_date: 'YYYY-MM-DD'. Returns an empty (zero-row, but
    correctly-schema'd) table if the lake has no data for that day —
    a day with genuinely no traffic is a valid input, not an error,
    and callers should be able to tell the difference from a lake
    that's missing entirely (see raise below)."""
    day_dir = LAKE_ROOT / "scan_events" / f"date={report_date}"
    if not day_dir.exists():
        if not LAKE_ROOT.exists():
            raise FileNotFoundError(
                f"lake root not found at {LAKE_ROOT} — is warehouse/lake_writer running?"
            )
        return _empty_table()

    dataset = ds.dataset(str(day_dir), format="parquet", partitioning="hive")
    table = dataset.to_table()
    return table


def _empty_table() -> pa.Table:
    schema = pa.schema(
        [
            ("event_id", pa.string()),
            ("package_id", pa.string()),
            ("station", pa.string()),
            ("scanner_id", pa.string()),
            ("scanned_at", pa.timestamp("ms", tz="UTC")),
            ("result", pa.string()),
            ("damage_type", pa.string()),
            ("damage_confidence", pa.float32()),
            ("item_id", pa.string()),
            # Reconstructed from the hive-partitioned hour= directory
            # name on a populated read (ds.dataset(..., partitioning="hive")
            # adds it as a real column) — included here too so an empty
            # day returns the same schema shape as a populated one,
            # rather than a table missing this column.
            ("hour", pa.int32()),
        ]
    )
    return pa.table({f.name: [] for f in schema}, schema=schema)
