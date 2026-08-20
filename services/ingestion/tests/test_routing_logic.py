"""Unit tests for route_for: pure function, no network involved.

These pin down the routing decision table itself, independent of whether
gRPC streaming plumbing works (that's test_stream_e2e.py's job).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "gen" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "common"))

from packagepb.v1 import common_pb2, routing_instruction_pb2, scan_event_pb2

from server import route_for


def _event(station, result=scan_event_pb2.SCAN_RESULT_OK, damage_type=None):
    ev = scan_event_pb2.ScanEvent(
        event_id="evt-1",
        package_id="pkg-1",
        station=station,
        result=result,
    )
    if damage_type is not None:
        ev.damage_assessment.damage_type = damage_type
    return ev


def test_intake_ok_routes_to_sort_a():
    instr = route_for(_event(common_pb2.STATION_TYPE_INTAKE))
    assert instr.action == routing_instruction_pb2.ROUTING_ACTION_PROCEED
    assert instr.next_station == common_pb2.STATION_TYPE_SORT_A
    assert instr.next_lane_id == "lane-SORT_A-1"
    assert instr.in_response_to_event_id == "evt-1"
    assert instr.package_id == "pkg-1"


def test_sort_a_ok_routes_to_sort_b():
    instr = route_for(_event(common_pb2.STATION_TYPE_SORT_A))
    assert instr.next_station == common_pb2.STATION_TYPE_SORT_B


def test_dispatch_ok_holds_as_final_station():
    instr = route_for(_event(common_pb2.STATION_TYPE_DISPATCH))
    assert instr.action == routing_instruction_pb2.ROUTING_ACTION_HOLD
    assert "final station" in instr.reason


def test_unreadable_scan_holds_for_manual_id():
    instr = route_for(_event(common_pb2.STATION_TYPE_SORT_A, result=scan_event_pb2.SCAN_RESULT_UNREADABLE))
    assert instr.action == routing_instruction_pb2.ROUTING_ACTION_HOLD
    assert "unreadable" in instr.reason


def test_damage_detected_flags_for_review_but_still_routes():
    instr = route_for(
        _event(
            common_pb2.STATION_TYPE_SORT_A,
            result=scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED,
            damage_type=scan_event_pb2.DAMAGE_TYPE_CRUSHED,
        )
    )
    assert instr.action == routing_instruction_pb2.ROUTING_ACTION_FLAG_FOR_REVIEW
    assert instr.next_station == common_pb2.STATION_TYPE_SORT_B
    assert "DAMAGE_TYPE_CRUSHED" in instr.reason
