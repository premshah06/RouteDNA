import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "gen" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "common"))

import asyncio

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from packagepb.v1 import alert_pb2, common_pb2, scan_event_pb2

from server import Broadcaster


def _scan_event(package_id="pkg-1", station=common_pb2.STATION_TYPE_SORT_A, epoch_ms=1_700_000_000_000):
    ts = Timestamp()
    ts.FromMilliseconds(epoch_ms)
    return scan_event_pb2.ScanEvent(
        event_id="evt-1", package_id=package_id, station=station, scanned_at=ts
    )


def test_apply_scan_event_updates_position_table():
    b = Broadcaster()
    b.apply_scan_event(_scan_event(package_id="pkg-1", station=common_pb2.STATION_TYPE_INTAKE))
    assert "pkg-1" in b.positions
    assert b.positions["pkg-1"].station == common_pb2.STATION_TYPE_INTAKE


def test_apply_scan_event_overwrites_previous_position():
    b = Broadcaster()
    b.apply_scan_event(_scan_event(package_id="pkg-1", station=common_pb2.STATION_TYPE_INTAKE))
    b.apply_scan_event(_scan_event(package_id="pkg-1", station=common_pb2.STATION_TYPE_SORT_A))
    assert b.positions["pkg-1"].station == common_pb2.STATION_TYPE_SORT_A
    assert len(b.positions) == 1


def test_snapshot_events_reflects_current_positions():
    b = Broadcaster()
    b.apply_scan_event(_scan_event(package_id="pkg-1"))
    b.apply_scan_event(_scan_event(package_id="pkg-2"))
    snapshot = b.snapshot_events()
    assert len(snapshot) == 2
    package_ids = {e.position_update.package_id for e in snapshot}
    assert package_ids == {"pkg-1", "pkg-2"}


@pytest.mark.asyncio
async def test_registered_client_receives_broadcast_scan_event():
    b = Broadcaster()
    queue = b.register_client()
    b.apply_scan_event(_scan_event(package_id="pkg-1"))
    event = queue.get_nowait()
    assert event.HasField("position_update")
    assert event.position_update.package_id == "pkg-1"


@pytest.mark.asyncio
async def test_registered_client_receives_broadcast_alert():
    b = Broadcaster()
    queue = b.register_client()
    alert = alert_pb2.Alert(alert_id="a1", package_id="pkg-1", alert_type=alert_pb2.ALERT_TYPE_STUCK_PACKAGE)
    b.apply_alert(alert)
    event = queue.get_nowait()
    assert event.HasField("alert")
    assert event.alert.alert_id == "a1"


@pytest.mark.asyncio
async def test_unregistered_client_does_not_receive_broadcasts():
    b = Broadcaster()
    queue = b.register_client()
    b.unregister_client(queue)
    b.apply_scan_event(_scan_event())
    assert queue.empty()


@pytest.mark.asyncio
async def test_multiple_clients_each_receive_broadcast():
    b = Broadcaster()
    q1 = b.register_client()
    q2 = b.register_client()
    b.apply_scan_event(_scan_event(package_id="pkg-1"))
    assert q1.get_nowait().position_update.package_id == "pkg-1"
    assert q2.get_nowait().position_update.package_id == "pkg-1"


@pytest.mark.asyncio
async def test_full_queue_drops_oldest_not_newest():
    # Regression-style test for the bounded-queue design: a slow client
    # must not block other clients, and when its queue fills, the
    # OLDEST pending event is dropped to make room for the newest one
    # (the client cares about catching up to "now", not replaying
    # everything it missed).
    b = Broadcaster()
    queue = asyncio.Queue(maxsize=2)
    b._clients.add(queue)

    b.apply_scan_event(_scan_event(package_id="pkg-1"))
    b.apply_scan_event(_scan_event(package_id="pkg-2"))
    # queue is now full (maxsize=2); this third event should evict pkg-1
    b.apply_scan_event(_scan_event(package_id="pkg-3"))

    remaining = [queue.get_nowait().position_update.package_id for _ in range(2)]
    assert remaining == ["pkg-2", "pkg-3"]
    assert queue.empty()
