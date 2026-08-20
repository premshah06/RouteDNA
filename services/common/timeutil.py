from datetime import datetime, timezone

from google.protobuf.timestamp_pb2 import Timestamp


def now_ts() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.now(timezone.utc))
    return ts
