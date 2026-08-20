"""Simulated scan station: gRPC client for IngestionService.StreamScans.

Opens one bidirectional stream and runs two concurrent coroutines against
it: one generates synthetic ScanEvents for a fixed set of packages at a
configurable interval, the other reads RoutingInstructions as they arrive
and logs them. This mirrors how a real station's scanner-feed and
sort-controller would be separate concerns sharing one stream.
"""

import argparse
import asyncio
import logging
import random
import uuid

import grpc

from packagepb.v1 import common_pb2, ingestion_service_pb2_grpc, scan_event_pb2
from timeutil import now_ts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("station_sim")

_STATION_NAME_TO_ENUM = {
    "intake": common_pb2.STATION_TYPE_INTAKE,
    "sort_a": common_pb2.STATION_TYPE_SORT_A,
    "sort_b": common_pb2.STATION_TYPE_SORT_B,
    "dispatch": common_pb2.STATION_TYPE_DISPATCH,
}


def _make_event(station: int, scanner_id: str, package_id: str) -> scan_event_pb2.ScanEvent:
    """Build one synthetic scan, occasionally simulating damage or an
    unreadable barcode so the ingestion service's branching logic
    actually gets exercised end to end, not just the happy path."""
    roll = random.random()
    event = scan_event_pb2.ScanEvent(
        event_id=str(uuid.uuid4()),
        package_id=package_id,
        station=station,
        scanner_id=scanner_id,
        scanned_at=now_ts(),
    )
    if roll < 0.05:
        event.result = scan_event_pb2.SCAN_RESULT_UNREADABLE
    elif roll < 0.15:
        event.result = scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED
        event.damage_assessment.damage_type = random.choice(
            [
                scan_event_pb2.DAMAGE_TYPE_CRUSHED,
                scan_event_pb2.DAMAGE_TYPE_TORN,
                scan_event_pb2.DAMAGE_TYPE_WET,
            ]
        )
        event.damage_assessment.confidence = round(random.uniform(0.7, 0.99), 2)
    else:
        event.result = scan_event_pb2.SCAN_RESULT_OK
    return event


async def _send_events(call, station: int, scanner_id: str, package_ids: list[str], interval: float, count: int):
    for i in range(count):
        package_id = package_ids[i % len(package_ids)]
        event = _make_event(station, scanner_id, package_id)
        await call.write(event)
        logger.info(
            "sent event_id=%s package_id=%s result=%s",
            event.event_id,
            event.package_id,
            scan_event_pb2.ScanResult.Name(event.result),
        )
        await asyncio.sleep(interval)
    await call.done_writing()


async def _receive_instructions(call):
    async for instruction in call:
        logger.info(
            "routing_instruction package_id=%s action=%s next_station=%s reason=%r",
            instruction.package_id,
            instruction.action,
            common_pb2.StationType.Name(instruction.next_station),
            instruction.reason,
        )


async def run(host: str, port: int, station_name: str, scanner_id: str, num_packages: int, interval: float, count: int):
    station = _STATION_NAME_TO_ENUM[station_name]
    package_ids = [str(uuid.uuid4()) for _ in range(num_packages)]

    async with grpc.aio.insecure_channel(f"{host}:{port}") as channel:
        stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
        call = stub.StreamScans()

        sender = asyncio.create_task(_send_events(call, station, scanner_id, package_ids, interval, count))
        receiver = asyncio.create_task(_receive_instructions(call))

        await sender
        await receiver


def main():
    parser = argparse.ArgumentParser(description="Simulated scan station")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--station", choices=_STATION_NAME_TO_ENUM.keys(), default="intake")
    parser.add_argument("--scanner-id", default="scanner-1")
    parser.add_argument("--num-packages", type=int, default=5, help="distinct packages to cycle through")
    parser.add_argument("--interval", type=float, default=0.5, help="seconds between scans")
    parser.add_argument("--count", type=int, default=20, help="total scans to send before closing")
    args = parser.parse_args()

    asyncio.run(
        run(args.host, args.port, args.station, args.scanner_id, args.num_packages, args.interval, args.count)
    )


if __name__ == "__main__":
    main()
