import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clickhouse_loader"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gen" / "python"))

from google.protobuf.timestamp_pb2 import Timestamp
from packagepb.v1 import alert_pb2, common_pb2

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


def test_rows_to_tsv_escapes_tabs_and_newlines():
    rows = [
        {
            "alert_id": "a1",
            "package_id": "p1",
            "alert_type": "ALERT_TYPE_MISROUTING",
            "severity": "SEVERITY_CRITICAL",
            "station": "STATION_TYPE_DISPATCH",
            "message": "line1\nline2\twith tab",
            "detected_at": 1700000000.123,
        }
    ]
    tsv = rows_to_tsv(rows)
    assert "\\n" in tsv  # escaped, not a literal newline breaking the row
    assert "\\t" in tsv
    # exactly one real newline: the trailing row terminator
    assert tsv.count("\n") == 1
    assert tsv.endswith("\n")


def test_rows_to_tsv_multiple_rows_one_line_each():
    rows = [
        {"alert_id": "a1", "package_id": "p1", "alert_type": "T1", "severity": "S1", "station": "ST1", "message": "m1", "detected_at": 1.0},
        {"alert_id": "a2", "package_id": "p2", "alert_type": "T2", "severity": "S2", "station": "ST2", "message": "m2", "detected_at": 2.0},
    ]
    tsv = rows_to_tsv(rows)
    lines = tsv.rstrip("\n").split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("a1\t")
    assert lines[1].startswith("a2\t")
