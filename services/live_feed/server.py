"""Checkpoint 7: live feed gRPC service.

Closes the loop: the frontend subscribes to LiveFeedService.Subscribe
and receives package position updates (derived from scan-events) and
alerts (forwarded from the alerts topic) in real time, over one
long-lived server-streaming call.

Two background consumers feed a fan-out broadcaster:
  - scan-events -> updates in-memory `positions` dict, broadcasts a
    PositionUpdate to every connected client.
  - alerts -> broadcasts an Alert to every connected client (no state
    kept; this service isn't the alert system of record — that's
    Checkpoint 6's warehouse).

State is deliberately in-memory only and lost on restart. History
already lives in the lake/warehouse (Checkpoint 6); this service's job
is "what's happening right now," not "what happened." A client that
connects gets an immediate snapshot of current positions (so the UI
isn't blank until the next scan happens to occur), then the live stream
going forward.

Fan-out design: each connected client gets its own asyncio.Queue.
Broadcasting is "best effort, bounded" — a slow/disconnected client's
queue can fill up; when it does, the OLDEST event is dropped to make
room for the newest (see _broadcast), rather than blocking every other
client on one slow reader, or growing memory unboundedly for a client
that never disconnects cleanly.
"""

import asyncio
import base64
import logging
import os
import sys
from typing import Optional

import grpc
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gen", "python"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from packagepb.v1 import (  # noqa: E402
    alert_pb2,
    live_feed_service_pb2,
    live_feed_service_pb2_grpc,
    scan_event_pb2,
)
from catalog import Catalog  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("live_feed")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
SCAN_EVENTS_TOPIC = "scan-events"
ALERTS_TOPIC = "alerts"

# Bounded per-client queue: a client that stops reading (network stall,
# crashed tab) must not let this service's memory grow without limit.
CLIENT_QUEUE_MAXSIZE = int(os.environ.get("CLIENT_QUEUE_MAXSIZE", 500))


def decode_scan_event(raw_value: bytes) -> scan_event_pb2.ScanEvent:
    return scan_event_pb2.ScanEvent.FromString(base64.b64decode(raw_value))


def decode_alert(raw_value: bytes) -> alert_pb2.Alert:
    return alert_pb2.Alert.FromString(base64.b64decode(raw_value))


class Broadcaster:
    """Owns the in-memory position table and the set of connected
    client queues. Not thread-safe by design — everything here runs on
    one asyncio event loop, so no locks are needed."""

    def __init__(self, item_names: Optional[dict] = None, item_categories: Optional[dict] = None):
        self.positions: dict[str, live_feed_service_pb2.PositionUpdate] = {}
        self._clients: set[asyncio.Queue] = set()
        # item_id -> name, loaded once at startup (see Catalog.all_names).
        # Missing/empty is fine — item_name just stays "" on the
        # PositionUpdate, same as a ScanEvent with no item_id attribute.
        self._item_names = item_names or {}
        # item_id -> ItemCategory enum value, same loading rationale as
        # item names (see Catalog.all_categories). Missing falls back to
        # ITEM_CATEGORY_UNSPECIFIED (proto3 default), same as item_name's
        # empty-string fallback above.
        self._item_categories = item_categories or {}

    def register_client(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_MAXSIZE)
        self._clients.add(queue)
        return queue

    def unregister_client(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)

    def snapshot_events(self) -> list:
        return [
            live_feed_service_pb2.LiveFeedEvent(position_update=p) for p in self.positions.values()
        ]

    def _broadcast(self, event: live_feed_service_pb2.LiveFeedEvent) -> None:
        for queue in self._clients:
            if queue.full():
                # Drop the oldest queued event for this client rather
                # than the newest — a client that's behind cares more
                # about catching up to "now" than replaying everything
                # it missed, and this bounds memory without blocking
                # every other client on one slow reader.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # lost a race with another producer; acceptable, best-effort

    def apply_scan_event(self, event: scan_event_pb2.ScanEvent) -> None:
        item_id = event.attributes.get("item_id", "")
        position = live_feed_service_pb2.PositionUpdate(
            package_id=event.package_id,
            station=event.station,
            updated_at=event.scanned_at,
            item_name=self._item_names.get(item_id, ""),
            item_category=self._item_categories.get(item_id, 0),
            damage_detected=(event.result == scan_event_pb2.SCAN_RESULT_DAMAGE_DETECTED),
        )
        self.positions[event.package_id] = position
        self._broadcast(live_feed_service_pb2.LiveFeedEvent(position_update=position))

    def apply_alert(self, alert: alert_pb2.Alert) -> None:
        self._broadcast(live_feed_service_pb2.LiveFeedEvent(alert=alert))


async def _consume_scan_events(broadcaster: Broadcaster) -> None:
    consumer = AIOKafkaConsumer(
        SCAN_EVENTS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=None,  # no consumer group: every live_feed instance sees every event independently
        auto_offset_reset="latest",  # "live" means from now, not full replay on every restart
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("consuming %s from %s", SCAN_EVENTS_TOPIC, KAFKA_BOOTSTRAP)
    try:
        async for msg in consumer:
            try:
                broadcaster.apply_scan_event(decode_scan_event(msg.value))
            except Exception:
                logger.exception("failed to decode scan event, skipping: offset=%s", msg.offset)
    finally:
        await consumer.stop()


async def _consume_alerts(broadcaster: Broadcaster) -> None:
    consumer = AIOKafkaConsumer(
        ALERTS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=None,
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("consuming %s from %s", ALERTS_TOPIC, KAFKA_BOOTSTRAP)
    try:
        async for msg in consumer:
            try:
                broadcaster.apply_alert(decode_alert(msg.value))
            except Exception:
                logger.exception("failed to decode alert, skipping: offset=%s", msg.offset)
    finally:
        await consumer.stop()


class LiveFeedServicer(live_feed_service_pb2_grpc.LiveFeedServiceServicer):
    def __init__(self, broadcaster: Broadcaster):
        self._broadcaster = broadcaster

    async def Subscribe(self, request, context):
        queue = self._broadcaster.register_client()
        peer = context.peer()
        logger.info("client connected: %s", peer)
        try:
            for event in self._broadcaster.snapshot_events():
                yield event
            while True:
                event = await queue.get()
                yield event
        finally:
            self._broadcaster.unregister_client(queue)
            logger.info("client disconnected: %s", peer)


def _load_catalog_lookups() -> tuple[dict[str, str], dict[str, int]]:
    try:
        catalog = Catalog()
    except FileNotFoundError:
        logger.warning("item catalog not found — position updates will show no item name/category")
        return {}, {}
    try:
        return catalog.all_names(), catalog.all_categories()
    finally:
        catalog.close()


async def serve(port: int = 50052) -> None:
    item_names, item_categories = _load_catalog_lookups()
    broadcaster = Broadcaster(item_names=item_names, item_categories=item_categories)

    server = grpc.aio.server()
    live_feed_service_pb2_grpc.add_LiveFeedServiceServicer_to_server(
        LiveFeedServicer(broadcaster), server
    )
    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)
    logger.info("live feed service listening on %s", listen_addr)

    consumer_tasks = [
        asyncio.create_task(_consume_scan_events(broadcaster)),
        asyncio.create_task(_consume_alerts(broadcaster)),
    ]

    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        for task in consumer_tasks:
            task.cancel()
        await asyncio.gather(*consumer_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(serve())
