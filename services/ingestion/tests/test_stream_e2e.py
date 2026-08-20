"""End-to-end test: real grpc.aio server + real grpc.aio client, bound to
an ephemeral local port. This is what actually proves the bidirectional
streaming contract works, as opposed to unit-testing route_for in
isolation.
"""

import sys
import uuid
from pathlib import Path

import grpc
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "gen" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "common"))

from packagepb.v1 import common_pb2, ingestion_service_pb2_grpc, routing_instruction_pb2, scan_event_pb2

from server import IngestionServicer


class FakeProducer:
    """In-memory stand-in for ScanEventProducer so streaming-contract
    tests don't depend on a live Kafka broker — that dependency is
    covered separately by test_kafka_integration.py."""

    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, package_id: str, event_bytes: bytes) -> None:
        self.published.append((package_id, event_bytes))


@pytest.fixture
async def running_server():
    fake_producer = FakeProducer()
    server = grpc.aio.server()
    ingestion_service_pb2_grpc.add_IngestionServiceServicer_to_server(
        IngestionServicer(fake_producer), server
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    try:
        yield port, fake_producer
    finally:
        await server.stop(grace=None)


@pytest.mark.asyncio
async def test_single_scan_gets_routed(running_server):
    port, fake_producer = running_server
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
        call = stub.StreamScans()

        event = scan_event_pb2.ScanEvent(
            event_id=str(uuid.uuid4()),
            package_id="pkg-e2e-1",
            station=common_pb2.STATION_TYPE_INTAKE,
            result=scan_event_pb2.SCAN_RESULT_OK,
        )
        await call.write(event)
        await call.done_writing()

        instructions = [instr async for instr in call]

    assert len(instructions) == 1
    assert instructions[0].package_id == "pkg-e2e-1"
    assert instructions[0].in_response_to_event_id == event.event_id
    assert instructions[0].action == routing_instruction_pb2.ROUTING_ACTION_PROCEED
    assert instructions[0].next_station == common_pb2.STATION_TYPE_SORT_A

    assert len(fake_producer.published) == 1
    published_key, published_bytes = fake_producer.published[0]
    assert published_key == "pkg-e2e-1"
    assert scan_event_pb2.ScanEvent.FromString(published_bytes) == event


@pytest.mark.asyncio
async def test_multiple_scans_preserve_order_and_correlation(running_server):
    port, fake_producer = running_server
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
        call = stub.StreamScans()

        event_ids = [str(uuid.uuid4()) for _ in range(5)]
        for i, eid in enumerate(event_ids):
            await call.write(
                scan_event_pb2.ScanEvent(
                    event_id=eid,
                    package_id=f"pkg-{i}",
                    station=common_pb2.STATION_TYPE_SORT_A,
                    result=scan_event_pb2.SCAN_RESULT_OK,
                )
            )
        await call.done_writing()

        instructions = [instr async for instr in call]

    assert len(instructions) == 5
    assert [instr.in_response_to_event_id for instr in instructions] == event_ids
    assert all(instr.next_station == common_pb2.STATION_TYPE_SORT_B for instr in instructions)
    assert len(fake_producer.published) == 5
    assert [key for key, _ in fake_producer.published] == [f"pkg-{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_unreadable_scan_is_held(running_server):
    port, fake_producer = running_server
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
        call = stub.StreamScans()

        await call.write(
            scan_event_pb2.ScanEvent(
                event_id=str(uuid.uuid4()),
                package_id="pkg-bad-barcode",
                station=common_pb2.STATION_TYPE_INTAKE,
                result=scan_event_pb2.SCAN_RESULT_UNREADABLE,
            )
        )
        await call.done_writing()

        instructions = [instr async for instr in call]

    assert len(instructions) == 1
    assert instructions[0].action == routing_instruction_pb2.ROUTING_ACTION_HOLD
    # unreadable is still a structurally valid event (has event_id/package_id)
    # so it's still published — Checkpoint 4/5 jobs need to see it to
    # explain why a package's journey has a gap.
    assert len(fake_producer.published) == 1


@pytest.mark.asyncio
async def test_invalid_event_is_dropped_not_published_or_routed(running_server):
    port, fake_producer = running_server
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
        call = stub.StreamScans()

        await call.write(scan_event_pb2.ScanEvent(event_id="", package_id="pkg-no-event-id"))
        await call.write(
            scan_event_pb2.ScanEvent(
                event_id=str(uuid.uuid4()),
                package_id="pkg-valid",
                station=common_pb2.STATION_TYPE_INTAKE,
                result=scan_event_pb2.SCAN_RESULT_OK,
            )
        )
        await call.done_writing()

        instructions = [instr async for instr in call]

    assert len(instructions) == 1
    assert instructions[0].package_id == "pkg-valid"
    assert len(fake_producer.published) == 1
    assert fake_producer.published[0][0] == "pkg-valid"
