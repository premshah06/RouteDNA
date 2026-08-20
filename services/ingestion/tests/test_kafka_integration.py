"""Integration test against a real Kafka broker (docker compose up kafka).

Separated from test_stream_e2e.py's fake-producer tests so the fast unit
suite doesn't require Docker. Run explicitly with:
    pytest services/ingestion/tests/test_kafka_integration.py -v
"""

import sys
import uuid
from pathlib import Path

import grpc
import pytest
from aiokafka import AIOKafkaConsumer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "gen" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "common"))

from packagepb.v1 import common_pb2, ingestion_service_pb2_grpc, scan_event_pb2

from kafka_producer import ScanEventProducer, TOPIC
from server import IngestionServicer

pytestmark = pytest.mark.kafka


@pytest.fixture
async def running_server_with_real_kafka():
    producer = ScanEventProducer(bootstrap_servers="localhost:9092")
    await producer.start()

    server = grpc.aio.server()
    ingestion_service_pb2_grpc.add_IngestionServiceServicer_to_server(
        IngestionServicer(producer), server
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    try:
        yield port
    finally:
        await server.stop(grace=None)
        await producer.stop()


@pytest.mark.asyncio
async def test_published_event_is_readable_from_kafka(running_server_with_real_kafka):
    port = running_server_with_real_kafka
    package_id = f"pkg-kafka-it-{uuid.uuid4()}"
    event_id = str(uuid.uuid4())

    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers="localhost:9092",
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        # consumer must be subscribed and assigned before we produce, or
        # "latest" offset reset means we'd miss the message
        await consumer.getmany(timeout_ms=2000)

        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub = ingestion_service_pb2_grpc.IngestionServiceStub(channel)
            call = stub.StreamScans()
            await call.write(
                scan_event_pb2.ScanEvent(
                    event_id=event_id,
                    package_id=package_id,
                    station=common_pb2.STATION_TYPE_INTAKE,
                    result=scan_event_pb2.SCAN_RESULT_OK,
                )
            )
            await call.done_writing()
            [_ async for _ in call]

        found = None
        for _ in range(10):
            batches = await consumer.getmany(timeout_ms=1000)
            for records in batches.values():
                for record in records:
                    if record.key.decode("utf-8") == package_id:
                        found = record
                        break
            if found:
                break

        assert found is not None, "published event was not observed on the scan-events topic"
        decoded = scan_event_pb2.ScanEvent.FromString(found.value)
        assert decoded.event_id == event_id
        assert decoded.package_id == package_id
    finally:
        await consumer.stop()
