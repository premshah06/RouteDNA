import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lake_writer"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gen" / "python"))

from google.protobuf.timestamp_pb2 import Timestamp
from packagepb.v1 import common_pb2, scan_event_pb2

from writer import decode_scan_event_row


def _b64_event(station=common_pb2.STATION_TYPE_SORT_A, result=scan_event_pb2.SCAN_RESULT_OK, epoch_ms=1_700_000_000_000, **kwargs):
    ts = Timestamp()
    ts.FromMilliseconds(epoch_ms)
    event = scan_event_pb2.ScanEvent(
        event_id="evt-1",
        package_id="pkg-1",
        station=station,
        scanner_id="scanner-1",
        scanned_at=ts,
        result=result,
    )
    if result == scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED:
        event.damage_assessment.damage_type = kwargs.get("damage_type", scan_event_pb2.DAMAGE_TYPE_CRUSHED)
        event.damage_assessment.confidence = kwargs.get("confidence", 0.9)
    return base64.b64encode(event.SerializeToString())


def test_decode_ok_scan_has_empty_damage_fields():
    row = decode_scan_event_row(_b64_event())
    assert row["event_id"] == "evt-1"
    assert row["package_id"] == "pkg-1"
    assert row["station"] == "STATION_TYPE_SORT_A"
    assert row["result"] == "SCAN_RESULT_OK"
    assert row["damage_type"] == ""
    assert row["damage_confidence"] == 0.0


def test_decode_damage_scan_populates_damage_fields():
    row = decode_scan_event_row(
        _b64_event(result=scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED, damage_type=scan_event_pb2.DAMAGE_TYPE_WET, confidence=0.87)
    )
    assert row["result"] == "SCAN_RESULT_DAMAGE_DETECTED"
    assert row["damage_type"] == "DAMAGE_TYPE_WET"
    assert abs(row["damage_confidence"] - 0.87) < 1e-6


def test_decode_derives_partition_from_scanned_at():
    # 2023-11-14T22:13:20Z
    row = decode_scan_event_row(_b64_event(epoch_ms=1_700_000_000_000))
    assert row["_partition"] == ("2023-11-14", "22")
