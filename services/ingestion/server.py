"""Ingestion gRPC server.

Checkpoint 2 proved the bidirectional streaming contract works. Checkpoint
3 adds Kafka publication as a decoupled side effect of the same RPC:
every validated ScanEvent is published to the scan-events topic (keyed by
package_id, see kafka_producer.py for the partitioning rationale) so
stream processing (Checkpoint 4+) can consume it independently of the
live gRPC session.

Kafka publication deliberately does NOT gate the RoutingInstruction sent
back down the stream — the physical sort decision is a real-time control
loop that must not stall waiting on Kafka. Publication happens
concurrently with routing; a slow or momentarily unavailable broker
delays analytics, not the conveyor.
"""

import asyncio
import logging

import grpc

from packagepb.v1 import (
    common_pb2,
    ingestion_service_pb2_grpc,
    routing_instruction_pb2,
    scan_event_pb2,
)
from timeutil import now_ts
from kafka_producer import ScanEventProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion")

# Fixed happy-path topology for Checkpoint 2's proof-of-concept routing.
# Real routing (destination-aware, damage-aware) lands once Package data
# and stream processing exist (Checkpoint 3+); this exists only to give
# StreamScans something non-trivial to send back down the stream.
_NEXT_STATION = {
    common_pb2.STATION_TYPE_INTAKE: common_pb2.STATION_TYPE_INDUCTION,
    common_pb2.STATION_TYPE_INDUCTION: common_pb2.STATION_TYPE_SORT_A,
    common_pb2.STATION_TYPE_SORT_A: common_pb2.STATION_TYPE_SORT_B,
    common_pb2.STATION_TYPE_SORT_B: common_pb2.STATION_TYPE_QC_CHECK,
    common_pb2.STATION_TYPE_QC_CHECK: common_pb2.STATION_TYPE_STAGING,
    common_pb2.STATION_TYPE_STAGING: common_pb2.STATION_TYPE_DISPATCH,
    common_pb2.STATION_TYPE_DISPATCH: common_pb2.STATION_TYPE_UNSPECIFIED,
}


def route_for(event: scan_event_pb2.ScanEvent) -> routing_instruction_pb2.RoutingInstruction:
    """Decide what a station should do with a package it just scanned."""
    instr = routing_instruction_pb2.RoutingInstruction(
        in_response_to_event_id=event.event_id,
        package_id=event.package_id,
        issued_at=now_ts(),
    )

    if event.result == scan_event_pb2.SCAN_RESULT_UNREADABLE:
        instr.action = routing_instruction_pb2.ROUTING_ACTION_HOLD
        instr.reason = "barcode unreadable, needs manual identification"
        return instr

    if event.result == scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED:
        instr.action = routing_instruction_pb2.ROUTING_ACTION_FLAG_FOR_REVIEW
        instr.reason = f"damage detected: {scan_event_pb2.DamageType.Name(event.damage_assessment.damage_type)}"
        # still tell the station where to send it physically
        next_station = _NEXT_STATION.get(event.station, common_pb2.STATION_TYPE_UNSPECIFIED)
        instr.next_station = next_station
        return instr

    next_station = _NEXT_STATION.get(event.station, common_pb2.STATION_TYPE_UNSPECIFIED)
    if next_station == common_pb2.STATION_TYPE_UNSPECIFIED:
        instr.action = routing_instruction_pb2.ROUTING_ACTION_HOLD
        instr.reason = "package has reached final station"
        return instr

    instr.action = routing_instruction_pb2.ROUTING_ACTION_PROCEED
    instr.next_station = next_station
    station_name = common_pb2.StationType.Name(next_station).removeprefix("STATION_TYPE_")
    instr.next_lane_id = f"lane-{station_name}-1"
    return instr


def is_valid(event: scan_event_pb2.ScanEvent) -> bool:
    """Minimum bar for an event to be worth publishing/routing at all.

    Structural presence, not business validation — event_id is required
    for Kafka idempotency/dedup downstream, package_id is required for
    the partition key and for every downstream join to have something to
    key on. A station bug that omits either shouldn't get to pollute the
    topic or waste a routing decision on an unroutable event.
    """
    return bool(event.event_id) and bool(event.package_id)


class IngestionServicer(ingestion_service_pb2_grpc.IngestionServiceServicer):
    def __init__(self, producer: ScanEventProducer):
        self._producer = producer

    async def StreamScans(self, request_iterator, context):
        peer = context.peer()
        logger.info("station connected: %s", peer)
        event_count = 0
        publish_tasks: set[asyncio.Task] = set()
        try:
            async for event in request_iterator:
                event_count += 1
                logger.info(
                    "scan received event_id=%s package_id=%s station=%s result=%s",
                    event.event_id,
                    event.package_id,
                    common_pb2.StationType.Name(event.station),
                    scan_event_pb2.ScanResult.Name(event.result),
                )

                if not is_valid(event):
                    logger.warning("dropping invalid event, missing event_id/package_id: %s", event)
                    continue

                # Fire-and-track: publication must not block the routing
                # response, but we still want to know if it failed rather
                # than silently losing events (see _log_publish_result).
                task = asyncio.create_task(
                    self._producer.publish(event.package_id, event.SerializeToString())
                )
                task.add_done_callback(lambda t, eid=event.event_id: _log_publish_result(t, eid))
                publish_tasks.add(task)
                task.add_done_callback(publish_tasks.discard)

                yield route_for(event)
        finally:
            if publish_tasks:
                await asyncio.gather(*publish_tasks, return_exceptions=True)
            logger.info("station disconnected: %s (%d events)", peer, event_count)


def _log_publish_result(task: asyncio.Task, event_id: str) -> None:
    exc = task.exception()
    if exc is not None:
        logger.error("failed to publish event_id=%s to kafka: %s", event_id, exc)


async def serve(port: int = 50051, kafka_bootstrap_servers: str = "localhost:9092") -> None:
    producer = ScanEventProducer(bootstrap_servers=kafka_bootstrap_servers)
    await producer.start()

    server = grpc.aio.server()
    ingestion_service_pb2_grpc.add_IngestionServiceServicer_to_server(
        IngestionServicer(producer), server
    )
    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)
    logger.info("ingestion service listening on %s", listen_addr)
    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(serve())
