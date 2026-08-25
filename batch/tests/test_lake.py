import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from thing_transfer_batch import lake

_SCHEMA = pa.schema(
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
    ]
)


def _write_fixture_partition(tmp_path, date: str, hour: str, rows: list):
    partition_dir = tmp_path / "scan_events" / f"date={date}" / f"hour={hour}"
    partition_dir.mkdir(parents=True)
    columns = {field.name: [row[field.name] for row in rows] for field in _SCHEMA}
    table = pa.table(columns, schema=_SCHEMA)
    pq.write_table(table, partition_dir / "batch-0001.parquet")


def test_read_scan_events_for_date_reads_all_hour_partitions(tmp_path, monkeypatch):
    monkeypatch.setattr(lake, "LAKE_ROOT", tmp_path)
    row = {
        "event_id": "evt-1",
        "package_id": "pkg-1",
        "station": "STATION_TYPE_INTAKE",
        "scanner_id": "scanner-1",
        "scanned_at": datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        "result": "SCAN_RESULT_OK",
        "damage_type": "",
        "damage_confidence": 0.0,
        "item_id": "item-1",
    }
    _write_fixture_partition(tmp_path, "2026-08-23", "10", [row])
    _write_fixture_partition(tmp_path, "2026-08-23", "11", [{**row, "event_id": "evt-2"}])

    table = lake.read_scan_events_for_date("2026-08-23")
    assert table.num_rows == 2
    assert set(table.column("event_id").to_pylist()) == {"evt-1", "evt-2"}


def test_read_scan_events_for_date_returns_empty_table_when_partition_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(lake, "LAKE_ROOT", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    table = lake.read_scan_events_for_date("2026-01-01")
    assert table.num_rows == 0
    # "hour" isn't in the write-fixture schema above (that's the schema
    # for one partition file) — a populated read reconstructs it from
    # the hive-partitioned directory name, so the empty-table schema
    # includes it too (see test_empty_table_schema_matches_populated_read_schema).
    assert table.schema.names == _SCHEMA.names + ["hour"]


def test_empty_table_schema_matches_populated_read_schema(tmp_path, monkeypatch):
    # Regression test for a real bug caught in review: the hand-rolled
    # empty-table schema previously didn't include "hour", which a
    # populated read reconstructs from the hive-partitioned directory
    # name — the two code paths must return the same shape, or code
    # that works against a populated day can break on an empty one.
    monkeypatch.setattr(lake, "LAKE_ROOT", tmp_path)
    row = {
        "event_id": "evt-1",
        "package_id": "pkg-1",
        "station": "STATION_TYPE_INTAKE",
        "scanner_id": "scanner-1",
        "scanned_at": datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        "result": "SCAN_RESULT_OK",
        "damage_type": "",
        "damage_confidence": 0.0,
        "item_id": "item-1",
    }
    _write_fixture_partition(tmp_path, "2026-08-23", "10", [row])
    populated = lake.read_scan_events_for_date("2026-08-23")
    empty = lake.read_scan_events_for_date("2026-01-01")
    assert empty.schema == populated.schema


def test_read_scan_events_for_date_raises_if_lake_root_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(lake, "LAKE_ROOT", tmp_path / "does-not-exist")
    with pytest.raises(FileNotFoundError):
        lake.read_scan_events_for_date("2026-01-01")
