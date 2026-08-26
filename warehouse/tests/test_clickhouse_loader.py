import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clickhouse_loader"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gen" / "python"))

from google.protobuf.timestamp_pb2 import Timestamp
from packagepb.v1 import alert_pb2, common_pb2, scan_event_pb2

from loader import decode_alert_row, rows_to_tsv, _resolve_station


def _b64_alert(alert_type=alert_pb2.ALERT_TYPE_STUCK_PACKAGE, epoch_ms=1_700_000_000_000):
    ts = Timestamp()
    ts.FromMilliseconds(epoch_ms)
    alert = alert_pb2.Alert(
        alert_id="alert-1",
        package_id="pkg-1",
        alert_type=alert_type,
        severity=alert_pb2.SEVERITY_WARNING,
        station=common_pb2.STATION_TYPE_SORT_A,
        message="test message",
        detected_at=ts,
    )
    return base64.b64encode(alert.SerializeToString())


def _base_row(**overrides) -> dict:
    row = {
        "alert_id": "a1",
        "package_id": "p1",
        "alert_type": "ALERT_TYPE_MISROUTING",
        "severity": "SEVERITY_CRITICAL",
        "station": "STATION_TYPE_DISPATCH",
        "message": "m",
        "detected_at": 1700000000.123,
        "stuck_duration_seconds": 0,
        "threshold_seconds": 0,
        "expected_station": "",
        "actual_station": "",
        "path_so_far": [],
        "damage_type": "",
        "damage_confidence": 0.0,
    }
    row.update(overrides)
    return row


def test_decode_alert_row_maps_enum_names_not_ints():
    row = decode_alert_row(_b64_alert())
    assert row["alert_id"] == "alert-1"
    assert row["alert_type"] == "ALERT_TYPE_STUCK_PACKAGE"
    assert row["severity"] == "SEVERITY_WARNING"
    assert row["station"] == "STATION_TYPE_SORT_A"
    assert row["message"] == "test message"
    assert abs(row["detected_at"] - 1_700_000_000.0) < 1e-3


def test_resolve_station_uses_top_level_field_for_non_misrouting_alerts():
    alert = alert_pb2.Alert(alert_type=alert_pb2.ALERT_TYPE_STUCK_PACKAGE, station=common_pb2.STATION_TYPE_SORT_B)
    assert _resolve_station(alert) == common_pb2.STATION_TYPE_SORT_B


def test_resolve_station_falls_back_to_misrouting_detail_actual_station():
    # Regression test: build_misrouting_alert (journey_correlator.py)
    # deliberately never sets the top-level station field for
    # misrouting alerts (alert.proto documents this — station is
    # ambiguous for a full-journey alert). Reading alert.station
    # directly would silently report every misrouting alert as
    # STATION_TYPE_UNSPECIFIED in the warehouse.
    alert = alert_pb2.Alert(alert_type=alert_pb2.ALERT_TYPE_MISROUTING)
    alert.misrouting_detail.actual_station = common_pb2.STATION_TYPE_SORT_B
    assert _resolve_station(alert) == common_pb2.STATION_TYPE_SORT_B


def test_decode_alert_row_misrouting_uses_actual_station():
    ts = Timestamp()
    ts.FromMilliseconds(1_700_000_000_000)
    alert = alert_pb2.Alert(
        alert_id="misrouting-1",
        package_id="pkg-1",
        alert_type=alert_pb2.ALERT_TYPE_MISROUTING,
        severity=alert_pb2.SEVERITY_WARNING,
        message="test",
        detected_at=ts,
    )
    alert.misrouting_detail.actual_station = common_pb2.STATION_TYPE_SORT_B
    row = decode_alert_row(base64.b64encode(alert.SerializeToString()))
    assert row["station"] == "STATION_TYPE_SORT_B"


def test_decode_alert_row_defaults_detail_columns_when_no_oneof_set():
    row = decode_alert_row(_b64_alert())
    # ALERT_TYPE_STUCK_PACKAGE with no stuck_detail actually set (proto3
    # allows this on the wire) — every detail column should stay at its
    # table default, not raise or silently pick up garbage.
    assert row["stuck_duration_seconds"] == 0
    assert row["threshold_seconds"] == 0
    assert row["expected_station"] == ""
    assert row["actual_station"] == ""
    assert row["path_so_far"] == []
    assert row["damage_type"] == ""
    assert row["damage_confidence"] == 0.0


def test_decode_alert_row_populates_stuck_detail():
    ts = Timestamp()
    ts.FromMilliseconds(1_700_000_000_000)
    alert = alert_pb2.Alert(
        alert_id="stuck-1",
        package_id="pkg-1",
        alert_type=alert_pb2.ALERT_TYPE_STUCK_PACKAGE,
        severity=alert_pb2.SEVERITY_WARNING,
        station=common_pb2.STATION_TYPE_SORT_A,
        message="stuck",
        detected_at=ts,
    )
    alert.stuck_detail.stuck_duration_seconds = 840
    alert.stuck_detail.threshold_seconds = 600
    row = decode_alert_row(base64.b64encode(alert.SerializeToString()))
    assert row["stuck_duration_seconds"] == 840
    assert row["threshold_seconds"] == 600
    # Other detail branches stay at their defaults.
    assert row["expected_station"] == ""
    assert row["damage_type"] == ""


def test_decode_alert_row_populates_misrouting_detail():
    ts = Timestamp()
    ts.FromMilliseconds(1_700_000_000_000)
    alert = alert_pb2.Alert(
        alert_id="misrouting-2",
        package_id="pkg-1",
        alert_type=alert_pb2.ALERT_TYPE_MISROUTING,
        severity=alert_pb2.SEVERITY_CRITICAL,
        message="misrouted",
        detected_at=ts,
    )
    alert.misrouting_detail.expected_station = common_pb2.STATION_TYPE_SORT_A
    alert.misrouting_detail.actual_station = common_pb2.STATION_TYPE_SORT_B
    alert.misrouting_detail.path_so_far.extend(
        [common_pb2.STATION_TYPE_INTAKE, common_pb2.STATION_TYPE_SORT_B]
    )
    row = decode_alert_row(base64.b64encode(alert.SerializeToString()))
    assert row["expected_station"] == "STATION_TYPE_SORT_A"
    assert row["actual_station"] == "STATION_TYPE_SORT_B"
    assert row["path_so_far"] == ["STATION_TYPE_INTAKE", "STATION_TYPE_SORT_B"]


def test_decode_alert_row_populates_damage_detail():
    ts = Timestamp()
    ts.FromMilliseconds(1_700_000_000_000)
    alert = alert_pb2.Alert(
        alert_id="damage-1",
        package_id="pkg-1",
        alert_type=alert_pb2.ALERT_TYPE_DAMAGE,
        severity=alert_pb2.SEVERITY_CRITICAL,
        station=common_pb2.STATION_TYPE_QC_CHECK,
        message="damaged",
        detected_at=ts,
    )
    alert.damage_detail.damage_type = scan_event_pb2.DAMAGE_TYPE_CRUSHED
    alert.damage_detail.confidence = 0.93
    row = decode_alert_row(base64.b64encode(alert.SerializeToString()))
    assert row["damage_type"] == "DAMAGE_TYPE_CRUSHED"
    assert abs(row["damage_confidence"] - 0.93) < 1e-4


def test_rows_to_tsv_escapes_tabs_and_newlines():
    rows = [_base_row(message="line1\nline2\twith tab")]
    tsv = rows_to_tsv(rows)
    assert "\\n" in tsv  # escaped, not a literal newline breaking the row
    assert "\\t" in tsv
    # exactly one real newline: the trailing row terminator
    assert tsv.count("\n") == 1
    assert tsv.endswith("\n")


def test_rows_to_tsv_multiple_rows_one_line_each():
    rows = [
        _base_row(alert_id="a1", package_id="p1", detected_at=1.0),
        _base_row(alert_id="a2", package_id="p2", detected_at=2.0),
    ]
    tsv = rows_to_tsv(rows)
    lines = tsv.rstrip("\n").split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("a1\t")
    assert lines[1].startswith("a2\t")


def test_rows_to_tsv_encodes_path_so_far_as_array_literal():
    rows = [_base_row(path_so_far=["STATION_TYPE_INTAKE", "STATION_TYPE_SORT_A"])]
    tsv = rows_to_tsv(rows)
    assert "['STATION_TYPE_INTAKE','STATION_TYPE_SORT_A']" in tsv


def test_rows_to_tsv_empty_path_so_far_is_empty_array_literal():
    rows = [_base_row(path_so_far=[])]
    tsv = rows_to_tsv(rows)
    assert "[]" in tsv
