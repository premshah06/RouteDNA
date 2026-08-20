"""Unit tests for the pure helper functions in stuck_package_detector.py:
base64 wire encoding and the key/timestamp extractors Flink calls per
element. Does not require a Flink cluster — that's covered separately by
a live integration test.

Run inside the Flink image (needs pyflink importable), with PYTHONPATH
covering both gen/python and stream_processing/jobs:
    docker run --rm \\
      -v "$(pwd)/gen/python:/opt/flink/usrlib/gen/python:ro" \\
      -v "$(pwd)/stream_processing:/opt/flink/usrlib/stream_processing:ro" \\
      -e PYTHONPATH=/opt/flink/usrlib/gen/python:/opt/flink/usrlib/stream_processing/jobs \\
      thing-transfer-flink:local \\
      bash -c "pip3 install --no-cache-dir pytest -q && \\
        python3 -m pytest /opt/flink/usrlib/stream_processing/tests/ -v -p no:cacheprovider"
See scripts/run_flink_tests.sh for a wrapper around this.
"""

import base64

from packagepb.v1 import common_pb2, scan_event_pb2
from google.protobuf.timestamp_pb2 import Timestamp

from stuck_package_detector import ScanEventTimestampAssigner, decode_scan_event, encode_alert, extract_package_id
from packagepb.v1 import alert_pb2


def _b64_event(package_id="pkg-1", station=common_pb2.STATION_TYPE_SORT_A, epoch_ms=1_700_000_000_000):
    ts = Timestamp()
    ts.FromMilliseconds(epoch_ms)
    event = scan_event_pb2.ScanEvent(
        event_id="evt-1",
        package_id=package_id,
        station=station,
        scanned_at=ts,
    )
    return base64.b64encode(event.SerializeToString()).decode("ascii")


def test_decode_scan_event_roundtrips():
    line = _b64_event(package_id="pkg-42")
    decoded = decode_scan_event(line)
    assert decoded.package_id == "pkg-42"


def test_extract_package_id():
    line = _b64_event(package_id="pkg-99")
    assert extract_package_id(line) == "pkg-99"


def test_timestamp_assigner_uses_scanned_at_not_record_timestamp():
    # WatermarkStrategy.with_timestamp_assigner requires an object
    # implementing TimestampAssigner.extract_timestamp — a bare function
    # type-checks in some PyFlink code paths but silently produces wrong
    # watermarks (registered timers that never fire). This test pins the
    # class-based contract so that regression can't reappear unnoticed.
    line = _b64_event(epoch_ms=1_700_000_000_000)
    assigner = ScanEventTimestampAssigner()
    # second arg (record_timestamp) is what Flink would pass as Kafka's
    # own timestamp; must be ignored in favor of the event's own
    # scanned_at field, since that's the actual event-time semantics
    # this job needs (see module docstring).
    assert assigner.extract_timestamp(line, 999) == 1_700_000_000_000


def test_encode_alert_produces_decodable_base64():
    alert = alert_pb2.Alert(
        alert_id="stuck-pkg-1-123",
        package_id="pkg-1",
        alert_type=alert_pb2.ALERT_TYPE_STUCK_PACKAGE,
    )
    encoded = encode_alert(alert)
    decoded = alert_pb2.Alert.FromString(base64.b64decode(encoded))
    assert decoded.package_id == "pkg-1"
    assert decoded.alert_type == alert_pb2.ALERT_TYPE_STUCK_PACKAGE
