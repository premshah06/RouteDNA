"""Unit tests for journey_correlator.py's pure decision logic
(build_misrouting_alert, _find_first_deviation). Does not require a
Flink cluster or session windows — those mechanics are Flink's own,
already covered by Checkpoint 4's live end-to-end verification of the
same watermark/timer foundation. What's specific and worth testing here
is: does out-of-order input get sorted correctly before judging the
path, and does the deviation logic handle each real journey shape
correctly.
"""

import base64

from google.protobuf.timestamp_pb2 import Timestamp
from packagepb.v1 import alert_pb2, common_pb2, scan_event_pb2

from journey_correlator import _find_first_deviation, build_misrouting_alert


def _b64_event(package_id, station, epoch_ms):
    ts = Timestamp()
    ts.FromMilliseconds(epoch_ms)
    event = scan_event_pb2.ScanEvent(
        event_id=f"evt-{station}-{epoch_ms}",
        package_id=package_id,
        station=station,
        scanned_at=ts,
    )
    return base64.b64encode(event.SerializeToString()).decode("ascii")


S = common_pb2
INTAKE, SORT_A, SORT_B, DISPATCH = (
    S.STATION_TYPE_INTAKE,
    S.STATION_TYPE_SORT_A,
    S.STATION_TYPE_SORT_B,
    S.STATION_TYPE_DISPATCH,
)


def test_find_first_deviation_clean_path():
    assert _find_first_deviation([INTAKE, SORT_A, SORT_B, DISPATCH]) == -1


def test_find_first_deviation_valid_prefix():
    # partial journey so far, no deviation yet (just incomplete)
    assert _find_first_deviation([INTAKE, SORT_A]) == -1


def test_find_first_deviation_skipped_station():
    # went straight from Intake to Sort B, skipping Sort A
    assert _find_first_deviation([INTAKE, SORT_B]) == 1


def test_find_first_deviation_ignores_trailing_scans_after_dispatch():
    # A scanner double-tap / retry / re-weigh at the dock after the
    # package has genuinely completed its journey must NOT be treated
    # as a deviation — the journey is already done once Dispatch is
    # reached, regardless of what (if anything) is scanned afterward.
    assert _find_first_deviation([INTAKE, SORT_A, SORT_B, DISPATCH, SORT_A]) == -1
    assert _find_first_deviation([INTAKE, SORT_A, SORT_B, DISPATCH, DISPATCH]) == -1


def test_clean_full_journey_produces_no_alert():
    events = [
        _b64_event("pkg-1", INTAKE, 1000),
        _b64_event("pkg-1", SORT_A, 2000),
        _b64_event("pkg-1", SORT_B, 3000),
        _b64_event("pkg-1", DISPATCH, 4000),
    ]
    assert build_misrouting_alert("pkg-1", events) is None


def test_trailing_duplicate_scan_after_dispatch_does_not_alert():
    # Regression test: a scanner double-tap at Dispatch (or any extra
    # scan landing in the same session after a genuinely completed
    # journey) previously made reached_dispatch False (path[-1] wasn't
    # DISPATCH) and mislabeled a successful delivery as CRITICAL
    # misrouting. The journey below IS complete — no alert should fire.
    events = [
        _b64_event("pkg-6", INTAKE, 1000),
        _b64_event("pkg-6", SORT_A, 2000),
        _b64_event("pkg-6", SORT_B, 3000),
        _b64_event("pkg-6", DISPATCH, 4000),
        _b64_event("pkg-6", DISPATCH, 4500),  # duplicate/retry scan
    ]
    assert build_misrouting_alert("pkg-6", events) is None


def test_out_of_order_arrival_still_judged_by_scan_time_not_arrival_order():
    # events handed to build_misrouting_alert in ARRIVAL order, which is
    # scrambled relative to their actual scanned_at — this is exactly
    # the out-of-order case the session window accumulates and this
    # function must sort correctly before judging the path.
    events = [
        _b64_event("pkg-1", DISPATCH, 4000),  # arrived first, scanned last
        _b64_event("pkg-1", INTAKE, 1000),
        _b64_event("pkg-1", SORT_B, 3000),
        _b64_event("pkg-1", SORT_A, 2000),
    ]
    assert build_misrouting_alert("pkg-1", events) is None


def test_skipped_station_produces_alert_with_correct_detail():
    events = [
        _b64_event("pkg-2", INTAKE, 1000),
        _b64_event("pkg-2", SORT_B, 2000),  # skipped Sort A
        _b64_event("pkg-2", DISPATCH, 3000),
    ]
    alert = build_misrouting_alert("pkg-2", events)
    assert alert is not None
    assert alert.package_id == "pkg-2"
    assert alert.alert_type == alert_pb2.ALERT_TYPE_MISROUTING
    assert alert.misrouting_detail.expected_station == SORT_A
    assert alert.misrouting_detail.actual_station == SORT_B
    assert list(alert.misrouting_detail.path_so_far) == [INTAKE, SORT_B, DISPATCH]
    # Regression test: detected_at was never set, silently defaulting to
    # protobuf's epoch-zero Timestamp (see the sibling stuck_package_detector
    # test with the same fix). Here it should be the last (sorted) event's
    # own scan time — DISPATCH at 3000ms in this journey.
    assert alert.detected_at.ToMilliseconds() == 3000
    assert alert.detected_at.ToMilliseconds() != 0


def test_journey_that_never_reaches_dispatch_is_flagged_critical():
    events = [
        _b64_event("pkg-3", INTAKE, 1000),
        _b64_event("pkg-3", SORT_A, 2000),
        _b64_event("pkg-3", SORT_B, 3000),
        # session gap elapsed here, no Dispatch scan ever arrived
    ]
    alert = build_misrouting_alert("pkg-3", events)
    assert alert is not None
    assert alert.severity == alert_pb2.SEVERITY_CRITICAL
    assert alert.misrouting_detail.expected_station == DISPATCH
    assert alert.misrouting_detail.actual_station == SORT_B


def test_alert_id_is_stable_across_repeated_calls_same_package():
    # stable (not timestamp-suffixed) alert_id is what lets a
    # late-arriving event's re-fired window UPDATE the same alert
    # rather than emit a duplicate — see module docstring.
    events_a = [_b64_event("pkg-4", INTAKE, 1000), _b64_event("pkg-4", SORT_B, 2000)]
    events_b = [
        _b64_event("pkg-4", INTAKE, 1000),
        _b64_event("pkg-4", SORT_B, 2000),
        _b64_event("pkg-4", SORT_A, 1500),  # late arrival, corrects the path
    ]
    alert_a = build_misrouting_alert("pkg-4", events_a)
    alert_b = build_misrouting_alert("pkg-4", events_b)
    assert alert_a.alert_id == alert_b.alert_id == "misrouting-pkg-4"


def test_empty_session_produces_no_alert():
    # defensive: shouldn't happen in practice (a session window can't
    # fire with zero elements) but must not crash if it does
    assert build_misrouting_alert("pkg-5", []) is None
