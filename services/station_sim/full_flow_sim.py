"""Realistic end-to-end facility traffic generator.

Unlike simulator.py (one station, one fixed package set, scans in
place forever — useful for exercising a single station in isolation,
not for demoing the facility), this script simulates actual package
flow: packages enter at Intake and advance through the real routing
chain (Intake -> Induction -> Sort A -> Sort B -> QC Check -> Staging
-> Dispatch, matching services/ingestion/server.py's _NEXT_STATION)
one hop at a time, on a randomized per-package dwell timer, then leave
the simulation once they reach Dispatch. New packages spawn on their
own timer so the facility keeps having fresh intake traffic instead of
draining to empty.

Single asyncio process, one shared IngestionService.StreamScans call —
much simpler than running 7 independent station processes, and
produces what the Live tab actually wants to show: uneven per-station
occupancy that rises and falls as packages move through, not a flat
count frozen at every station.
"""

import argparse
import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field

import grpc

from packagepb.v1 import common_pb2, ingestion_service_pb2_grpc, scan_event_pb2
from catalog import Catalog
from timeutil import now_ts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("full_flow_sim")

# Matches services/ingestion/server.py's _NEXT_STATION and
# frontend/src/constants.ts's STATIONS order — the facility's one real
# linear routing chain, every package passes through all seven in order.
_ROUTE = [
    common_pb2.STATION_TYPE_INTAKE,
    common_pb2.STATION_TYPE_INDUCTION,
    common_pb2.STATION_TYPE_SORT_A,
    common_pb2.STATION_TYPE_SORT_B,
    common_pb2.STATION_TYPE_QC_CHECK,
    common_pb2.STATION_TYPE_STAGING,
    common_pb2.STATION_TYPE_DISPATCH,
]
_SCANNER_ID_BY_STATION = {
    station: f"scanner-{common_pb2.StationType.Name(station).removeprefix('STATION_TYPE_').lower()}"
    for station in _ROUTE
}


@dataclass
class Package:
    package_id: str
    item_id: str
    item_name: str
    route_index: int = 0
    next_scan_at: float = 0.0


@dataclass
class SimState:
    packages: dict[str, Package] = field(default_factory=dict)


def _make_event(package: Package) -> scan_event_pb2.ScanEvent:
    """Same occasional-damage/unreadable branching as simulator.py's
    _make_event, so this generator exercises the same downstream
    paths (damage alerts, misrouting checks) — just driven by one
    package's actual position in the route instead of a fixed station."""
    station = _ROUTE[package.route_index]
    roll = random.random()
    event = scan_event_pb2.ScanEvent(
        event_id=str(uuid.uuid4()),
        package_id=package.package_id,
        station=station,
        scanner_id=_SCANNER_ID_BY_STATION[station],
        scanned_at=now_ts(),
    )
    if package.item_id:
        event.attributes["item_id"] = package.item_id
    if roll < 0.05:
        event.result = scan_event_pb2.SCAN_RESULT_UNREADABLE
    elif roll < 0.12:
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


def _spawn_package(catalog: Catalog, now: float, dwell_min: float, dwell_max: float) -> Package:
    item_id = catalog.sample_item_ids(1)[0]
    item = catalog.get(item_id)
    return Package(
        package_id=str(uuid.uuid4()),
        item_id=item_id,
        item_name=item.name if item else "",
        route_index=0,
        next_scan_at=now + random.uniform(dwell_min, dwell_max),
    )


async def _drive(
    call,
    state: SimState,
    catalog: Catalog,
    spawn_interval: float,
    dwell_min: float,
    dwell_max: float,
    max_active: int,
    tick: float,
) -> None:
    loop = asyncio.get_event_loop()
    next_spawn_at = loop.time()

    while True:
        now = loop.time()

        if now >= next_spawn_at and len(state.packages) < max_active:
            package = _spawn_package(catalog, now, dwell_min, dwell_max)
            state.packages[package.package_id] = package
            next_spawn_at = now + spawn_interval

        due = [p for p in state.packages.values() if now >= p.next_scan_at]
        for package in due:
            event = _make_event(package)
            await call.write(event)
            station_name = common_pb2.StationType.Name(_ROUTE[package.route_index])
            logger.info(
                "package_id=%s station=%s item=%r result=%s",
                package.package_id,
                station_name,
                package.item_name or "<unknown item>",
                scan_event_pb2.ScanResult.Name(event.result),
            )

            if package.route_index >= len(_ROUTE) - 1:
                # Reached Dispatch — leaves the simulated facility, same
                # as a real package would (live_feed's own position
                # eviction sweep handles the frontend side of this).
                del state.packages[package.package_id]
            else:
                package.route_index += 1
                package.next_scan_at = now + random.uniform(dwell_min, dwell_max)

        await asyncio.sleep(tick)


async def _receive_instructions(call) -> None:
    async for instruction in call:
        pass  # logged at _drive's per-scan granularity already; avoid doubling log volume


async def run(
    host: str,
    port: int,
    spawn_interval: float,
    dwell_min: float,
    dwell_max: float,
    max_active: int,
    tick: float,
) -> None:
    state = SimState()
    catalog = Catalog()
    try:
        async with grpc.aio.insecure_channel(f"{host}:{port}") as channel:
            stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
            call = stub.StreamScans()
            driver = asyncio.create_task(
                _drive(call, state, catalog, spawn_interval, dwell_min, dwell_max, max_active, tick)
            )
            receiver = asyncio.create_task(_receive_instructions(call))
            await asyncio.gather(driver, receiver)
    finally:
        catalog.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Realistic end-to-end facility traffic generator")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--spawn-interval", type=float, default=2.0, help="seconds between new packages entering at Intake")
    parser.add_argument("--dwell-min", type=float, default=4.0, help="min seconds a package stays at a station before advancing")
    parser.add_argument("--dwell-max", type=float, default=12.0, help="max seconds a package stays at a station before advancing")
    parser.add_argument("--max-active", type=int, default=60, help="cap on packages in the facility at once")
    parser.add_argument("--tick", type=float, default=0.5, help="scheduler poll interval")
    args = parser.parse_args()

    asyncio.run(
        run(
            args.host,
            args.port,
            args.spawn_interval,
            args.dwell_min,
            args.dwell_max,
            args.max_active,
            args.tick,
        )
    )


if __name__ == "__main__":
    main()
