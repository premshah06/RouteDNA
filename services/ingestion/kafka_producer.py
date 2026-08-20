"""Kafka publication for validated ScanEvents.

Partitioning: keyed by package_id. This guarantees every event for a given
package lands on the same partition and is therefore delivered to
consumers in produce order — a package's scans are never reordered across
partitions. That guarantee is what Checkpoint 5's journey correlation
depends on: it can trust per-package ordering within a partition instead
of having to reconstruct order from scratch across the whole topic.

Partitioning by station instead would create exactly 4 hot partitions
(one per StationType) that can't be spread across more than 4 consumers
and gives no per-package ordering guarantee at all. Partitioning by
event_id (effectively random) would maximize spread but destroys the
per-package ordering guarantee entirely. package_id is the only key that
serves the actual downstream consumer.

Wire encoding: values are base64-encoded protobuf bytes, not raw bytes.
PyFlink 1.19's DataStream Kafka connector has no built-in raw-byte-array
(de)serialization schema without writing custom Java, but ships
SimpleStringSchema (UTF-8 strings) natively — base64 lets the Flink jobs
(stream_processing/jobs/) use that directly instead of maintaining a
custom JAR. ~33% wire overhead, accepted for local-dev scale.
"""

import base64
import logging

from aiokafka import AIOKafkaProducer

logger = logging.getLogger("ingestion.kafka_producer")

TOPIC = "scan-events"


class ScanEventProducer:
    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            acks="all",
            enable_idempotence=True,
            key_serializer=lambda k: k.encode("utf-8"),
            value_serializer=lambda v: base64.b64encode(v),
        )
        await self._producer.start()
        logger.info("kafka producer connected to %s", self._bootstrap_servers)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            logger.info("kafka producer stopped")

    async def publish(self, package_id: str, event_bytes: bytes) -> None:
        """event_bytes is the raw protobuf-serialized message; base64
        encoding onto the wire happens in value_serializer above, kept
        out of caller code (server.py) so the encoding lives in exactly
        one place."""
        assert self._producer is not None, "call start() before publish()"
        await self._producer.send_and_wait(TOPIC, value=event_bytes, key=package_id)
